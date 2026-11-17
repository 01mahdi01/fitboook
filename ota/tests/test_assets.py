"""Tests for ``GET /api/updates/assets`` (content types, caching, safety)."""

from __future__ import annotations

from .factories import (
    DEFAULT_ASSET_BYTES,
    DEFAULT_BUNDLE_BYTES,
    TEST_RUNTIME_VERSION,
    OTATestCase,
    add_file,
)


class AssetServingTests(OTATestCase):
    def setUp(self) -> None:
        super().setUp()
        self.release = self.publish().release
        self.platform_metadata = self.release.platform_metadata("android")
        self.bundle_path = self.platform_metadata["bundle"]
        self.asset_path = self.platform_metadata["assets"][0]["path"]

    def _get_asset(self, asset: str, **overrides: str):
        params = {
            "asset": asset,
            "runtimeVersion": TEST_RUNTIME_VERSION,
            "platform": "android",
        }
        params.update(overrides)
        return self.client.get("/api/updates/assets", data=params)

    def test_serves_launch_bundle_with_correct_headers(self):
        response = self._get_asset(self.bundle_path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), DEFAULT_BUNDLE_BYTES)
        self.assertEqual(response["Content-Type"], "application/javascript")
        self.assertEqual(response["Content-Length"], str(len(DEFAULT_BUNDLE_BYTES)))
        self.assertEqual(
            response["Cache-Control"], "public, max-age=31536000, immutable"
        )

    def test_serves_asset_with_metadata_content_type(self):
        response = self._get_asset(self.asset_path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), DEFAULT_ASSET_BYTES)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["Content-Length"], str(len(DEFAULT_ASSET_BYTES)))

    def test_missing_asset_parameter_is_400(self):
        response = self.client.get(
            "/api/updates/assets",
            data={"runtimeVersion": TEST_RUNTIME_VERSION, "platform": "android"},
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_platform_is_400(self):
        response = self.client.get(
            "/api/updates/assets",
            data={"asset": self.bundle_path, "runtimeVersion": TEST_RUNTIME_VERSION},
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_platform_is_400(self):
        response = self._get_asset(self.bundle_path, platform="windows")
        self.assertEqual(response.status_code, 400)

    def test_missing_runtime_version_is_400(self):
        response = self.client.get(
            "/api/updates/assets",
            data={"asset": self.bundle_path, "platform": "android"},
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_runtime_version_is_400(self):
        response = self._get_asset(self.bundle_path, runtimeVersion="../1.2.2")
        self.assertEqual(response.status_code, 400)

    def test_unknown_runtime_version_is_404(self):
        response = self._get_asset(self.bundle_path, runtimeVersion="9.9.9")
        self.assertEqual(response.status_code, 404)

    def test_unknown_asset_is_404(self):
        response = self._get_asset("assets/does-not-exist.png")
        self.assertEqual(response.status_code, 404)

    def test_files_not_listed_in_metadata_are_not_served(self):
        add_file(self.release.storage_directory, "private/secret.txt", b"top-secret")
        response = self._get_asset("private/secret.txt")
        self.assertEqual(response.status_code, 404)
        # ... and the internal metadata file is not exposed either.
        self.assertEqual(self._get_asset("metadata.json").status_code, 404)

    def test_path_traversal_is_blocked(self):
        for malicious in (
            "../../etc/passwd",
            "assets/../../../../etc/passwd",
            "/etc/passwd",
            "C:\\Windows\\win.ini",
        ):
            with self.subTest(asset=malicious):
                response = self._get_asset(malicious)
                self.assertEqual(response.status_code, 400)

    def test_percent_encoded_traversal_is_blocked(self):
        # Sent as a raw query string so the server decodes %2F only once (like a
        # real attacker would), which must still be rejected as traversal.
        response = self.client.get(
            "/api/updates/assets"
            "?asset=..%2f..%2fetc%2fpasswd"
            "&runtimeVersion=1.2.2&platform=android"
        )
        self.assertEqual(response.status_code, 400)

    def test_double_encoded_traversal_is_treated_as_plain_filename(self):
        # After one decode this is a single path segment with no separators, so
        # it is simply an unknown asset (404), never a file-system escape.
        response = self._get_asset("..%2f..%2fetc%2fpasswd")
        self.assertEqual(response.status_code, 404)

    def test_post_is_not_allowed(self):
        response = self.client.post("/api/updates/assets")
        self.assertEqual(response.status_code, 405)

    def test_assets_of_previous_releases_stay_downloadable(self):
        first = self.release
        first_metadata = first.platform_metadata("android")
        first_bundle = first_metadata["bundle"]

        second = self.publish().release
        self.assertNotEqual(first.update_id, second.update_id)

        response = self._get_asset(first_bundle)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), DEFAULT_BUNDLE_BYTES)

    def test_assets_of_deactivated_releases_stay_downloadable(self):
        self.release.is_active = False
        self.release.save(update_fields=["is_active"])
        response = self._get_asset(self.bundle_path)
        self.assertEqual(response.status_code, 200)

    def test_assets_are_platform_scoped_but_search_all_releases(self):
        response = self._get_asset(self.bundle_path, platform="ios")
        self.assertEqual(response.status_code, 404)
