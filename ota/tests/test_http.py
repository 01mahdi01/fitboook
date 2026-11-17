"""Unit tests for the multipart/protocol HTTP helpers."""

from __future__ import annotations

from django.test import SimpleTestCase

from ota.http import (
    IMMUTABLE_CACHE,
    NO_CACHE,
    NO_UPDATE_DIRECTIVE,
    build_multipart_response,
    directive_response,
    encode_multipart_mixed,
    json_error,
    manifest_json_response,
    manifest_multipart_response,
)

BOUNDARY = "ota-test-boundary"


class MultipartEncodingTests(SimpleTestCase):
    def test_wire_format_is_rfc2046_compliant(self):
        body = encode_multipart_mixed(
            [
                ("manifest", "application/json; charset=utf-8", b'{"id":"x"}'),
                ("extensions", "application/json", b'{"a":1}'),
            ],
            BOUNDARY,
        )
        self.assertTrue(body.startswith(b"--ota-test-boundary\r\n"))
        self.assertIn(b'Content-Disposition: form-data; name="manifest"\r\n', body)
        self.assertIn(b"Content-Type: application/json; charset=utf-8\r\n", body)
        self.assertIn(b'Content-Disposition: form-data; name="extensions"\r\n', body)
        self.assertTrue(body.endswith(b"--ota-test-boundary--\r\n"))
        # Two opening boundary lines + the closing one.
        self.assertEqual(body.count(b"--ota-test-boundary"), 3)

    def test_empty_parts_still_produce_closing_boundary(self):
        body = encode_multipart_mixed([], BOUNDARY)
        self.assertEqual(body, b"--ota-test-boundary--\r\n")

    def test_boundary_is_required(self):
        with self.assertRaises(ValueError):
            encode_multipart_mixed([], "")


class MultipartResponseTests(SimpleTestCase):
    def test_protocol_headers_and_content_type(self):
        response = build_multipart_response(
            [("directive", "application/json", b'{"type":"noUpdateAvailable"}')]
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["expo-protocol-version"], "1")
        self.assertEqual(response["expo-sfv-version"], "0")
        self.assertEqual(response["Cache-Control"], NO_CACHE)
        content_type = response["Content-Type"]
        self.assertTrue(content_type.startswith("multipart/mixed; boundary="))
        boundary = content_type.split("boundary=", 1)[1]
        self.assertIn(boundary.encode(), response.content)

    def test_directive_response_contains_no_update_available(self):
        response = directive_response()
        self.assertIn(b'{"type":"noUpdateAvailable"}', response.content)
        self.assertEqual(NO_UPDATE_DIRECTIVE, {"type": "noUpdateAvailable"})

    def test_manifest_multipart_response_has_both_parts(self):
        response = manifest_multipart_response(
            {"id": "abc"}, {"assetRequestHeaders": {"k": {}}}
        )
        self.assertIn(b'name="manifest"', response.content)
        self.assertIn(b'name="extensions"', response.content)

    def test_protocol0_json_response_is_not_cached(self):
        response = manifest_json_response({"id": "abc", "runtimeVersion": "1.2.2"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response["Cache-Control"], NO_CACHE)
        self.assertJSONEqual(response.content, {"id": "abc", "runtimeVersion": "1.2.2"})

    def test_immutable_cache_policy_for_assets(self):
        self.assertEqual(IMMUTABLE_CACHE, "public, max-age=31536000, immutable")

    def test_json_error_helper(self):
        response = json_error("boom", 418)
        self.assertEqual(response.status_code, 418)
        self.assertJSONEqual(response.content, {"error": "boom"})
