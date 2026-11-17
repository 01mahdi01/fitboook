"""End-to-end tests for ``GET /api/updates/manifest`` (Expo Updates v1 protocol)."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase

from ota.models import UpdateSettings
from ota.paths import safe_relative_path

from .factories import (
    DEFAULT_ASSET_BYTES,
    DEFAULT_BUNDLE_BYTES,
    TEST_RUNTIME_VERSION,
    OTATestCase,
    latest_release,
    parse_multipart_json,
    parse_multipart_response,
)


class ProtocolOneManifestTests(OTATestCase):
    def setUp(self) -> None:
        super().setUp()
        self.result = self.publish(
            notes="manifest test",
            expo_config={"name": "Fitboook", "version": "1.2.2"},
        )
        self.release = self.result.release

    def _manifest(self) -> dict:
        response = self.client.get(
            "/api/updates/manifest", headers=self.manifest_headers(protocol=1)
        )
        self.assertEqual(response.status_code, 200, response.content)
        return parse_multipart_json(response, "manifest")

    def test_response_headers_and_parts(self):
        response = self.client.get(
            "/api/updates/manifest", headers=self.manifest_headers(protocol=1)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["expo-protocol-version"], "1")
        self.assertEqual(response["expo-sfv-version"], "0")
        self.assertEqual(response["Cache-Control"], "private, max-age=0")
        self.assertTrue(
            response["Content-Type"].startswith("multipart/mixed; boundary=")
        )
        parts = parse_multipart_response(response)
        self.assertEqual(set(parts), {"manifest", "extensions"})
        self.assertEqual(parts["manifest"].get_content_type(), "application/json")
        self.assertEqual(parts["extensions"].get_content_type(), "application/json")

    def test_manifest_identity_fields(self):
        manifest = self._manifest()
        self.assertEqual(manifest["id"], self.release.update_id)
        self.assertRegex(
            manifest["id"],
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        )
        self.assertEqual(manifest["runtimeVersion"], TEST_RUNTIME_VERSION)
        self.assertRegex(
            manifest["createdAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
        )
        self.assertEqual(manifest["metadata"], {})

    def test_launch_asset_shape(self):
        manifest = self._manifest()
        launch = manifest["launchAsset"]
        expected_hash = hashlib.sha256(DEFAULT_BUNDLE_BYTES).digest()
        expected_b64 = base64.urlsafe_b64encode(expected_hash).decode().rstrip("=")
        expected_key = hashlib.md5(DEFAULT_BUNDLE_BYTES).hexdigest()

        self.assertEqual(launch["hash"], expected_b64)
        self.assertEqual(launch["key"], expected_key)
        self.assertEqual(launch["contentType"], "application/javascript")
        self.assertEqual(launch["fileExtension"], ".bundle")
        self.assertTrue(
            launch["url"].startswith("https://api.fitboook.ir/api/updates/assets?")
        )

    def test_asset_url_query_matches_release(self):
        manifest = self._manifest()
        android_metadata = self.release.platform_metadata("android")
        launch_url = urlsplit(manifest["launchAsset"]["url"])
        query = parse_qs(launch_url.query)
        self.assertEqual(query["asset"], [android_metadata["bundle"]])
        self.assertEqual(query["runtimeVersion"], [TEST_RUNTIME_VERSION])
        self.assertEqual(query["platform"], ["android"])

        asset_url = urlsplit(manifest["assets"][0]["url"])
        asset_query = parse_qs(asset_url.query)
        self.assertEqual(asset_query["asset"], [android_metadata["assets"][0]["path"]])
        self.assertEqual(query["runtimeVersion"], [TEST_RUNTIME_VERSION])

    def test_assets_array_shape(self):
        manifest = self._manifest()
        self.assertEqual(len(manifest["assets"]), 1)
        asset = manifest["assets"][0]
        expected_hash = hashlib.sha256(DEFAULT_ASSET_BYTES).digest()
        expected_b64 = base64.urlsafe_b64encode(expected_hash).decode().rstrip("=")
        self.assertEqual(asset["hash"], expected_b64)
        self.assertEqual(asset["key"], hashlib.md5(DEFAULT_ASSET_BYTES).hexdigest())
        self.assertEqual(asset["contentType"], "image/png")
        self.assertEqual(asset["fileExtension"], ".png")
        self.assertIn("/api/updates/assets?", asset["url"])

    def test_extra_contains_expo_client_config(self):
        manifest = self._manifest()
        self.assertEqual(
            manifest["extra"]["expoClient"],
            {"name": "Fitboook", "version": "1.2.2"},
        )

    def test_extra_expo_client_is_empty_without_config(self):
        self.publish(
            export_dir=self.make_export(platform="android"),
            runtime_version="1.2.3",
        )
        response = self.client.get(
            "/api/updates/manifest",
            headers=self.manifest_headers(runtime_version="1.2.3", protocol=1),
        )
        manifest = parse_multipart_json(response, "manifest")
        self.assertEqual(manifest["extra"], {"expoClient": {}})

    def test_extensions_declare_asset_request_headers_for_every_asset(self):
        manifest = self._manifest()
        response = self.client.get(
            "/api/updates/manifest", headers=self.manifest_headers(protocol=1)
        )
        extensions = parse_multipart_json(response, "extensions")
        expected_keys = {manifest["launchAsset"]["key"]} | {
            asset["key"] for asset in manifest["assets"]
        }
        self.assertEqual(set(extensions["assetRequestHeaders"]), expected_keys)
        for value in extensions["assetRequestHeaders"].values():
            self.assertEqual(value, {})

    def test_manifest_urls_are_downloadable(self):
        manifest = self._manifest()
        bundle_response = self.get_asset(manifest["launchAsset"]["url"])
        self.assertEqual(bundle_response.status_code, 200)
        self.assertEqual(
            b"".join(bundle_response.streaming_content), DEFAULT_BUNDLE_BYTES
        )
        self.assertEqual(bundle_response["Content-Type"], "application/javascript")

        asset_response = self.get_asset(manifest["assets"][0]["url"])
        self.assertEqual(asset_response.status_code, 200)
        self.assertEqual(
            b"".join(asset_response.streaming_content), DEFAULT_ASSET_BYTES
        )
        self.assertEqual(asset_response["Content-Type"], "image/png")

    def test_no_update_directive_when_client_is_current(self):
        response = self.client.get(
            "/api/updates/manifest",
            headers=self.manifest_headers(
                protocol=1, **{"expo-current-update-id": self.release.update_id}
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("multipart/mixed"))
        parts = parse_multipart_response(response)
        self.assertEqual(set(parts), {"directive"})
        directive = json.loads(parts["directive"].get_payload(decode=True))
        self.assertEqual(directive, {"type": "noUpdateAvailable"})

    def test_manifest_served_when_client_has_different_update(self):
        response = self.client.get(
            "/api/updates/manifest",
            headers=self.manifest_headers(
                protocol=1, **{"expo-current-update-id": "stale-id"}
            ),
        )
        self.assertEqual(
            parse_multipart_json(response, "manifest")["id"], self.release.update_id
        )

    def test_no_update_directive_when_no_release(self):
        response = self.client.get(
            "/api/updates/manifest",
            headers=self.manifest_headers(runtime_version="9.9.9", protocol=1),
        )
        self.assertEqual(response.status_code, 200)
        directive = json.loads(
            parse_multipart_response(response)["directive"].get_payload(decode=True)
        )
        self.assertEqual(directive["type"], "noUpdateAvailable")

    def test_no_update_directive_when_platform_not_in_release(self):
        response = self.client.get(
            "/api/updates/manifest",
            headers=self.manifest_headers(platform="ios", protocol=1),
        )
        directive = json.loads(
            parse_multipart_response(response)["directive"].get_payload(decode=True)
        )
        self.assertEqual(directive["type"], "noUpdateAvailable")

    def test_expo_embedded_update_id_is_accepted(self):
        response = self.client.get(
            "/api/updates/manifest",
            headers=self.manifest_headers(
                protocol=1, **{"expo-embedded-update-id": "embedded"}
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            parse_multipart_json(response, "manifest")["id"], self.release.update_id
        )


class ProtocolZeroManifestTests(OTATestCase):
    def setUp(self) -> None:
        super().setUp()
        self.release = self.publish().release

    def test_protocol_zero_returns_plain_json_manifest(self):
        response = self.client.get(
            "/api/updates/manifest", headers=self.manifest_headers(protocol=0)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response["Cache-Control"], "private, max-age=0")
        manifest = response.json()
        self.assertEqual(manifest["id"], self.release.update_id)
        self.assertEqual(manifest["runtimeVersion"], TEST_RUNTIME_VERSION)
        self.assertIn("launchAsset", manifest)

    def test_missing_protocol_header_is_treated_as_protocol_zero(self):
        headers = self.manifest_headers(protocol=None)
        response = self.client.get("/api/updates/manifest", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_protocol_zero_returns_404_without_release(self):
        response = self.client.get(
            "/api/updates/manifest",
            headers=self.manifest_headers(runtime_version="9.9.9", protocol=0),
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_protocol_zero_returns_404_for_unknown_platform_release(self):
        response = self.client.get(
            "/api/updates/manifest",
            headers=self.manifest_headers(platform="ios", protocol=0),
        )
        self.assertEqual(response.status_code, 404)


class ManifestValidationTests(OTATestCase):
    def test_missing_platform_header_is_400(self):
        response = self.client.get(
            "/api/updates/manifest",
            headers={
                "expo-runtime-version": TEST_RUNTIME_VERSION,
                "expo-protocol-version": "1",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("expo-platform", response.json()["error"])

    def test_invalid_platform_is_400(self):
        response = self.client.get(
            "/api/updates/manifest",
            headers=self.manifest_headers(platform="windows", protocol=1),
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_runtime_version_is_400(self):
        response = self.client.get(
            "/api/updates/manifest",
            headers={"expo-platform": "android", "expo-protocol-version": "1"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("runtime", response.json()["error"].lower())

    def test_invalid_runtime_version_is_400(self):
        response = self.client.get(
            "/api/updates/manifest",
            headers=self.manifest_headers(runtime_version="../evil", protocol=1),
        )
        self.assertEqual(response.status_code, 400)

    def test_non_numeric_protocol_version_is_400(self):
        response = self.client.get(
            "/api/updates/manifest", headers=self.manifest_headers(protocol="banana")
        )
        self.assertEqual(response.status_code, 400)

    def test_unsupported_protocol_version_is_406(self):
        response = self.client.get(
            "/api/updates/manifest", headers=self.manifest_headers(protocol=2)
        )
        self.assertEqual(response.status_code, 406)

    def test_query_parameters_are_accepted_as_fallback(self):
        self.publish()
        response = self.client.get(
            "/api/updates/manifest",
            data={"platform": "android", "runtime-version": TEST_RUNTIME_VERSION},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_get_only(self):
        response = self.client.post("/api/updates/manifest")
        self.assertEqual(response.status_code, 405)


class ManifestKillSwitchTests(OTATestCase):
    def setUp(self) -> None:
        super().setUp()
        self.release = self.publish().release
        settings_row = UpdateSettings.get_solo()
        settings_row.enabled = False
        settings_row.save(update_fields=["enabled", "updated_at"])

    def test_protocol_one_returns_no_update_directive_when_disabled(self):
        response = self.client.get(
            "/api/updates/manifest", headers=self.manifest_headers(protocol=1)
        )
        self.assertEqual(response.status_code, 200)
        parts = parse_multipart_response(response)
        self.assertEqual(set(parts), {"directive"})
        directive = json.loads(parts["directive"].get_payload(decode=True))
        self.assertEqual(directive["type"], "noUpdateAvailable")

    def test_protocol_zero_returns_404_when_disabled(self):
        response = self.client.get(
            "/api/updates/manifest", headers=self.manifest_headers(protocol=0)
        )
        self.assertEqual(response.status_code, 404)

    def test_assets_remain_downloadable_when_disabled(self):
        metadata = self.release.platform_metadata("android")
        response = self.client.get(
            "/api/updates/assets",
            data={
                "asset": metadata["bundle"],
                "runtimeVersion": TEST_RUNTIME_VERSION,
                "platform": "android",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), DEFAULT_BUNDLE_BYTES)


class ManifestIsolationTests(OTATestCase):
    def test_runtime_versions_do_not_leak_into_each_other(self):
        old = self.publish(runtime_version="1.2.2").release
        new = self.publish(runtime_version="1.2.3").release
        old_manifest = parse_multipart_json(
            self.client.get(
                "/api/updates/manifest",
                headers=self.manifest_headers(runtime_version="1.2.2", protocol=1),
            ),
            "manifest",
        )
        new_manifest = parse_multipart_json(
            self.client.get(
                "/api/updates/manifest",
                headers=self.manifest_headers(runtime_version="1.2.3", protocol=1),
            ),
            "manifest",
        )
        self.assertEqual(old_manifest["id"], old.update_id)
        self.assertEqual(new_manifest["id"], new.update_id)
        self.assertNotEqual(old_manifest["id"], new_manifest["id"])

    def test_admin_variant_runtime_version_publishes_separately(self):
        main = self.publish(runtime_version=TEST_RUNTIME_VERSION).release
        admin = self.publish(runtime_version="1.2.2-admin").release
        admin_manifest = parse_multipart_json(
            self.client.get(
                "/api/updates/manifest",
                headers=self.manifest_headers(
                    runtime_version="1.2.2-admin", protocol=1
                ),
            ),
            "manifest",
        )
        self.assertEqual(admin_manifest["id"], admin.update_id)
        self.assertEqual(latest_release("1.2.2", "android").update_id, main.update_id)

    def test_new_publish_becomes_latest_manifest(self):
        first = self.publish(notes="one").release
        self.assertEqual(
            parse_multipart_json(
                self.client.get(
                    "/api/updates/manifest", headers=self.manifest_headers(protocol=1)
                ),
                "manifest",
            )["id"],
            first.update_id,
        )
        second = self.publish(notes="two").release
        self.assertEqual(
            parse_multipart_json(
                self.client.get(
                    "/api/updates/manifest", headers=self.manifest_headers(protocol=1)
                ),
                "manifest",
            )["id"],
            second.update_id,
        )


class ManifestPathContractTests(SimpleTestCase):
    def test_manifest_and_asset_paths_are_not_guess_work(self):
        from django.urls import resolve

        manifest_match = resolve("/api/updates/manifest")
        asset_match = resolve("/api/updates/assets")
        self.assertEqual(manifest_match.url_name, "manifest")
        self.assertEqual(asset_match.url_name, "assets")
        self.assertEqual(manifest_match.app_name, "ota")

    def test_safe_relative_path_round_trips_real_bundle_names(self):
        rel = "_expo/static/js/android/entry-0123456789abcdef.hbc"
        self.assertEqual(safe_relative_path(rel), rel)
        self.assertRegex(rel, re.compile(r"^[A-Za-z0-9_./-]+$"))
