"""Tests for the JSON admin/CI API under ``/api/admin/updates/``."""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from ota.models import Release, UpdateSettings

from .factories import (
    TEST_ADMIN_TOKEN,
    TEST_RUNTIME_VERSION,
    OTATestCase,
    make_zip,
    parse_multipart_json,
    parse_multipart_response,
)

AUTH_HEADERS = {"X-Admin-Key": TEST_ADMIN_TOKEN}
LIST_URL = "/api/admin/updates/"
PUBLISH_URL = "/api/admin/updates/publish/"
SETTINGS_URL = "/api/admin/updates/settings/"


class AdminAuthTests(OTATestCase):
    def test_list_requires_authentication(self):
        self.assertEqual(self.client.get(LIST_URL).status_code, 401)
        self.assertEqual(
            self.client.get(LIST_URL, headers={"X-Admin-Key": "wrong-key"}).status_code,
            403,
        )

    def test_list_accepts_admin_token(self):
        response = self.client.get(LIST_URL, headers=AUTH_HEADERS)
        self.assertEqual(response.status_code, 200)

    def test_list_accepts_staff_session(self):
        user = get_user_model().objects.create_user(
            **{get_user_model().USERNAME_FIELD: "staff"}, password="pw", is_staff=True
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get(LIST_URL).status_code, 200)

    def test_non_staff_session_is_rejected(self):
        user = get_user_model().objects.create_user(**{get_user_model().USERNAME_FIELD: "user"}, password="pw")
        self.client.force_login(user)
        self.assertEqual(self.client.get(LIST_URL).status_code, 401)

    def test_disabled_admin_api_when_token_not_configured(self):
        with self.settings(OTA_ADMIN_TOKEN=""):
            response = self.client.get(LIST_URL, headers={"X-Admin-Key": "anything"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("OTA_ADMIN_TOKEN", response.json()["error"])

    def test_publish_requires_authentication(self):
        response = self.client.post(
            PUBLISH_URL,
            data={
                "runtimeVersion": TEST_RUNTIME_VERSION,
                "platform": "android",
                "bundle": SimpleUploadedFile("dist.zip", make_zip(self.make_export())),
            },
        )
        self.assertEqual(response.status_code, 401)


class AdminReleaseListTests(OTATestCase):
    def test_lists_releases_newest_first(self):
        first = self.publish(notes="one").release
        second = self.publish(notes="two").release

        response = self.client.get(LIST_URL, headers=AUTH_HEADERS)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        ids = [item["id"] for item in payload["releases"]]
        self.assertEqual(ids, [second.pk, first.pk])
        newest = payload["releases"][0]
        self.assertEqual(newest["updateId"], second.update_id)
        self.assertTrue(newest["isLatest"])
        self.assertFalse(payload["releases"][1]["isLatest"])
        self.assertEqual(newest["notes"], "two")
        self.assertIn("storagePath", newest)
        self.assertTrue(newest["publishedAt"].endswith("Z"))

    def test_filters_by_runtime_version_and_platform(self):
        self.publish(runtime_version="1.2.2")
        ios_release = self.publish(platform="ios", runtime_version="1.2.3").release

        response = self.client.get(
            LIST_URL + "?runtimeVersion=1.2.3", headers=AUTH_HEADERS
        )
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["releases"][0]["id"], ios_release.pk)

        response = self.client.get(LIST_URL + "?platform=ios", headers=AUTH_HEADERS)
        self.assertEqual(response.json()["count"], 1)

    def test_active_filter_and_invalid_value(self):
        self.publish()
        second = self.publish().release
        second.is_active = False
        second.save(update_fields=["is_active"])

        response = self.client.get(LIST_URL + "?active=false", headers=AUTH_HEADERS)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["releases"][0]["id"], second.pk)

        bad = self.client.get(LIST_URL + "?active=maybe", headers=AUTH_HEADERS)
        self.assertEqual(bad.status_code, 400)

    def test_post_is_not_allowed(self):
        self.assertEqual(
            self.client.post(LIST_URL, headers=AUTH_HEADERS).status_code, 405
        )


class AdminPublishEndpointTests(OTATestCase):
    def _publish_request(self, zip_bytes: bytes | None = None, **fields: str):
        export_dir = self.make_export()
        payload = {
            "runtimeVersion": TEST_RUNTIME_VERSION,
            "platform": "android",
            "notes": "published by ci",
            "bundle": SimpleUploadedFile(
                "dist-ota.zip",
                zip_bytes if zip_bytes is not None else make_zip(export_dir),
            ),
        }
        payload.update(fields)
        return self.client.post(PUBLISH_URL, data=payload, headers=AUTH_HEADERS)

    def test_publishes_release_from_zip(self):
        response = self._publish_request()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["created"])
        self.assertTrue(body["isLatest"])

        release = Release.objects.get()
        self.assertEqual(body["release"]["id"], release.pk)
        self.assertEqual(body["release"]["updateId"], release.update_id)
        self.assertEqual(release.notes, "published by ci")
        self.assertIsNone(release.created_by)

        manifest_response = self.client.get(
            "/api/updates/manifest", headers=self.manifest_headers(protocol=1)
        )
        self.assertEqual(
            parse_multipart_json(manifest_response, "manifest")["id"], release.update_id
        )

    def test_publish_records_staff_user(self):
        user = get_user_model().objects.create_user(
            **{get_user_model().USERNAME_FIELD: "staff"}, password="pw", is_staff=True
        )
        self.client.force_login(user)
        export_dir = self.make_export()
        response = self.client.post(
            PUBLISH_URL,
            data={
                "runtimeVersion": TEST_RUNTIME_VERSION,
                "platform": "android",
                "bundle": SimpleUploadedFile("dist.zip", make_zip(export_dir)),
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Release.objects.get().created_by_id, user.pk)

    def test_activate_false_field(self):
        response = self._publish_request(activate="false")
        self.assertEqual(response.status_code, 201)
        self.assertFalse(Release.objects.get().is_active)
        self.assertFalse(response.json()["isLatest"])

    def test_invalid_activate_value_is_400(self):
        self.assertEqual(self._publish_request(activate="perhaps").status_code, 400)

    def test_missing_bundle_is_400(self):
        response = self.client.post(
            PUBLISH_URL,
            data={"runtimeVersion": TEST_RUNTIME_VERSION, "platform": "android"},
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("bundle", response.json()["error"])

    def test_invalid_platform_is_400(self):
        self.assertEqual(self._publish_request(platform="windows").status_code, 400)

    def test_missing_runtime_version_is_400(self):
        response = self._publish_request(runtimeVersion="")
        self.assertEqual(response.status_code, 400)

    def test_invalid_runtime_version_is_400(self):
        self.assertEqual(
            self._publish_request(runtimeVersion="../evil").status_code, 400
        )

    def test_oversized_upload_is_413(self):
        with self.settings(OTA_MAX_UPLOAD_BYTES=16):
            response = self._publish_request()
        self.assertEqual(response.status_code, 413)

    def test_not_a_zip_is_400(self):
        response = self._publish_request(zip_bytes=b"not a zip at all")
        self.assertEqual(response.status_code, 400)

    def test_get_is_not_allowed(self):
        self.assertEqual(
            self.client.get(PUBLISH_URL, headers=AUTH_HEADERS).status_code, 405
        )


class AdminRollbackEndpointTests(OTATestCase):
    def setUp(self) -> None:
        super().setUp()
        self.first = self.publish(notes="one").release
        self.second = self.publish(notes="two").release

    def _manifest_id(self) -> str:
        response = self.client.get(
            "/api/updates/manifest", headers=self.manifest_headers(protocol=1)
        )
        return parse_multipart_json(response, "manifest")["id"]

    def test_deactivate_rolls_back_to_previous_release(self):
        self.assertEqual(self._manifest_id(), self.second.update_id)

        response = self.client.post(
            f"/api/admin/updates/{self.second.pk}/deactivate/", headers=AUTH_HEADERS
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["latestReleaseId"], self.first.pk)
        self.assertFalse(body["release"]["active"])
        self.assertEqual(self._manifest_id(), self.first.update_id)

    def test_activate_restores_newer_release(self):
        self.second.is_active = False
        self.second.save(update_fields=["is_active"])
        self.assertEqual(self._manifest_id(), self.first.update_id)

        response = self.client.post(
            f"/api/admin/updates/{self.second.pk}/activate/", headers=AUTH_HEADERS
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["latestReleaseId"], self.second.pk)
        self.assertEqual(self._manifest_id(), self.second.update_id)

    def test_deactivating_an_old_release_keeps_newest(self):
        response = self.client.post(
            f"/api/admin/updates/{self.first.pk}/deactivate/", headers=AUTH_HEADERS
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._manifest_id(), self.second.update_id)

    def test_unknown_release_is_404(self):
        self.assertEqual(
            self.client.post(
                "/api/admin/updates/999999/deactivate/", headers=AUTH_HEADERS
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                "/api/admin/updates/999999/activate/", headers=AUTH_HEADERS
            ).status_code,
            404,
        )

    def test_rollback_endpoints_require_auth(self):
        self.assertEqual(
            self.client.post(
                f"/api/admin/updates/{self.second.pk}/deactivate/"
            ).status_code,
            401,
        )


class AdminSettingsEndpointTests(OTATestCase):
    def test_get_settings(self):
        response = self.client.get(SETTINGS_URL, headers=AUTH_HEADERS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["settings"]["enabled"], True)

    def test_post_json_disables_kill_switch(self):
        response = self.client.post(
            SETTINGS_URL,
            data=json.dumps({"enabled": False}),
            content_type="application/json",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["settings"]["enabled"])
        self.assertFalse(UpdateSettings.get_solo().enabled)

        manifest_response = self.client.get(
            "/api/updates/manifest", headers=self.manifest_headers(protocol=1)
        )
        directive = json.loads(
            parse_multipart_response(manifest_response)["directive"].get_payload(
                decode=True
            )
        )
        self.assertEqual(directive["type"], "noUpdateAvailable")

    def test_post_form_enables_kill_switch(self):
        UpdateSettings.objects.filter(pk=1).update(enabled=False)
        response = self.client.post(
            SETTINGS_URL, data={"enabled": "true"}, headers=AUTH_HEADERS
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["settings"]["enabled"])

    def test_missing_enabled_field_is_400(self):
        response = self.client.post(SETTINGS_URL, data={}, headers=AUTH_HEADERS)
        self.assertEqual(response.status_code, 400)

    def test_invalid_boolean_is_400(self):
        response = self.client.post(
            SETTINGS_URL, data={"enabled": "sometimes"}, headers=AUTH_HEADERS
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_json_is_400(self):
        response = self.client.post(
            SETTINGS_URL,
            data="{broken",
            content_type="application/json",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 400)
