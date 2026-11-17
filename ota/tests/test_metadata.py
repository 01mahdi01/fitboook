"""Unit tests for metadata parsing, update-id derivation and hashing."""

from __future__ import annotations

import json

from django.test import SimpleTestCase

from ota.exceptions import InvalidBundleError
from ota.metadata import (
    content_type_for_extension,
    file_digests,
    format_update_id,
    load_expo_config,
    parse_export_metadata,
    read_export_metadata,
    sha256_hex,
    update_id_from_metadata_bytes,
)

from .factories import OTATestCase, add_file, make_export_dir


def document_bytes(document: dict) -> bytes:
    return json.dumps(document).encode("utf-8")


def valid_document() -> dict:
    return {
        "version": 0,
        "bundler": "metro",
        "fileMetadata": {
            "android": {
                "bundle": "_expo/static/js/android/entry-abc.hbc",
                "assets": [{"path": "assets/logo-abc.png", "ext": "png"}],
            }
        },
    }


class UpdateIdTests(SimpleTestCase):
    """The update id must match the proven nodoost/Expo derivation exactly."""

    def test_known_sha256_and_update_id_vector(self):
        digest = sha256_hex(b"abc")
        self.assertEqual(
            digest, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
        self.assertEqual(
            format_update_id(digest), "ba7816bf-8f01-cfea-4141-40de5dae2223"
        )
        self.assertEqual(
            update_id_from_metadata_bytes(b"abc"),
            "ba7816bf-8f01-cfea-4141-40de5dae2223",
        )

    def test_update_id_is_uuid_shaped_and_deterministic(self):
        first = update_id_from_metadata_bytes(b'{"version":0}')
        second = update_id_from_metadata_bytes(b'{"version":0}')
        self.assertEqual(first, second)
        self.assertRegex(
            first,
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        )

    def test_different_metadata_produces_different_ids(self):
        self.assertNotEqual(
            update_id_from_metadata_bytes(b'{"a":1}'),
            update_id_from_metadata_bytes(b'{"a":2}'),
        )

    def test_short_digest_is_rejected(self):
        with self.assertRaises(ValueError):
            format_update_id("abc")


class ContentTypeTests(SimpleTestCase):
    def test_known_extensions_map_to_expected_mime_types(self):
        cases = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "svg": "image/svg+xml",
            "ttf": "font/ttf",
            "woff2": "font/woff2",
            "mp4": "video/mp4",
            "mp3": "audio/mpeg",
            "hbc": "application/javascript",
            "json": "application/json",
        }
        for extension, expected in cases.items():
            with self.subTest(extension=extension):
                self.assertEqual(content_type_for_extension(extension), expected)

    def test_leading_dot_and_case_are_normalized(self):
        self.assertEqual(content_type_for_extension(".PNG"), "image/png")

    def test_unknown_or_empty_extension_is_octet_stream(self):
        self.assertEqual(content_type_for_extension(""), "application/octet-stream")
        self.assertEqual(content_type_for_extension(None), "application/octet-stream")
        self.assertEqual(
            content_type_for_extension("unknownext"), "application/octet-stream"
        )


class FileDigestTests(OTATestCase):
    def test_known_digest_vector(self):
        path = self.tmp_dir / "abc.bin"
        path.write_bytes(b"abc")
        digest, key = file_digests(path)
        self.assertEqual(digest, "ungWv48Bz-pBQUDeXa4iI7ADYaOWF3qctBD_YfIAFa0")
        self.assertEqual(key, "900150983cd24fb0d6963f7d28e17f72")


class ParseMetadataTests(OTATestCase):
    def test_valid_metadata_round_trip(self):
        export_dir = make_export_dir(self.tmp_dir)
        metadata = read_export_metadata(export_dir)

        self.assertEqual(metadata.version, 0)
        self.assertEqual(metadata.bundler, "metro")
        self.assertEqual(set(metadata.file_metadata), {"android"})
        android = metadata.require_platform("android")
        self.assertTrue(android.bundle.endswith(".hbc"))
        self.assertEqual(len(android.assets), 1)
        self.assertEqual(android.assets[0].ext, "png")
        self.assertEqual(android.assets[0].file_extension, ".png")
        raw = (export_dir / "metadata.json").read_bytes()
        self.assertEqual(metadata.raw, raw)
        self.assertEqual(metadata.update_id, update_id_from_metadata_bytes(raw))
        self.assertEqual(
            metadata.document["fileMetadata"]["android"]["bundle"], android.bundle
        )

    def test_multiple_platforms_are_parsed(self):
        document = {
            "version": 0,
            "bundler": "metro",
            "fileMetadata": {
                "android": {"bundle": "_expo/static/js/android/a.hbc", "assets": []},
                "ios": {"bundle": "_expo/static/js/ios/i.hbc", "assets": []},
            },
        }
        export_dir = make_export_dir(self.tmp_dir, metadata_document=document)
        metadata = read_export_metadata(export_dir)
        self.assertEqual(set(metadata.file_metadata), {"android", "ios"})
        self.assertEqual(
            metadata.require_platform("ios").bundle, "_expo/static/js/ios/i.hbc"
        )

    def test_platform_names_are_lowercased(self):
        document = {
            "version": 0,
            "fileMetadata": {
                "Android": {"bundle": "_expo/static/js/android/a.hbc", "assets": []},
            },
        }
        metadata = parse_export_metadata(document_bytes(document))
        self.assertIn("android", metadata.file_metadata)

    def test_extension_is_derived_from_path_when_missing(self):
        document = {
            "version": 0,
            "fileMetadata": {
                "android": {
                    "bundle": "bundle.hbc",
                    "assets": [{"path": "assets/photo.jpeg"}],
                }
            },
        }
        metadata = parse_export_metadata(document_bytes(document))
        asset = metadata.require_platform("android").assets[0]
        self.assertEqual(asset.ext, "jpeg")
        self.assertEqual(asset.file_extension, ".jpeg")

    def test_version_and_bundler_are_optional(self):
        metadata = parse_export_metadata(
            document_bytes(
                {"fileMetadata": {"android": {"bundle": "b.hbc", "assets": []}}}
            )
        )
        self.assertEqual(metadata.version, 0)
        self.assertEqual(metadata.bundler, "")

    def test_missing_metadata_file_is_rejected(self):
        empty_dir = self.tmp_dir / "empty-export"
        empty_dir.mkdir()
        with self.assertRaises(InvalidBundleError) as caught:
            read_export_metadata(empty_dir)
        self.assertIn("metadata.json", str(caught.exception))

    def test_nonexistent_export_directory_is_rejected(self):
        with self.assertRaises(InvalidBundleError):
            read_export_metadata(self.tmp_dir / "does-not-exist")

    def test_invalid_json_is_rejected(self):
        with self.assertRaises(InvalidBundleError) as caught:
            parse_export_metadata(b"{not json")
        self.assertIn("not valid JSON", str(caught.exception))

    def test_non_object_root_is_rejected(self):
        with self.assertRaises(InvalidBundleError):
            parse_export_metadata(b"[]")

    def test_missing_file_metadata_is_rejected(self):
        with self.assertRaises(InvalidBundleError) as caught:
            parse_export_metadata(document_bytes({"version": 0}))
        self.assertIn("fileMetadata", str(caught.exception))

    def test_empty_file_metadata_is_rejected(self):
        with self.assertRaises(InvalidBundleError):
            parse_export_metadata(document_bytes({"version": 0, "fileMetadata": {}}))

    def test_bad_version_type_is_rejected(self):
        with self.assertRaises(InvalidBundleError):
            parse_export_metadata(
                document_bytes(
                    {
                        "version": "zero",
                        "fileMetadata": {"android": {"bundle": "b.hbc", "assets": []}},
                    }
                )
            )

    def test_bundle_path_traversal_is_rejected(self):
        document = valid_document()
        document["fileMetadata"]["android"]["bundle"] = "../../etc/passwd"
        with self.assertRaises(InvalidBundleError) as caught:
            parse_export_metadata(document_bytes(document))
        self.assertIn("traversal", str(caught.exception).lower())

    def test_absolute_asset_path_is_rejected(self):
        document = valid_document()
        document["fileMetadata"]["android"]["assets"] = [
            {"path": "/etc/passwd", "ext": "txt"}
        ]
        with self.assertRaises(InvalidBundleError):
            parse_export_metadata(document_bytes(document))

    def test_duplicate_asset_is_rejected(self):
        document = valid_document()
        document["fileMetadata"]["android"]["assets"] = [
            {"path": "assets/a.png", "ext": "png"},
            {"path": "assets/a.png", "ext": "png"},
        ]
        with self.assertRaises(InvalidBundleError) as caught:
            parse_export_metadata(document_bytes(document))
        self.assertIn("duplicate", str(caught.exception).lower())

    def test_asset_pointing_to_internal_file_is_rejected(self):
        document = valid_document()
        document["fileMetadata"]["android"]["assets"] = [
            {"path": "metadata.json", "ext": "json"}
        ]
        with self.assertRaises(InvalidBundleError):
            parse_export_metadata(document_bytes(document))

    def test_require_platform_lists_available_platforms(self):
        metadata = parse_export_metadata(document_bytes(valid_document()))
        with self.assertRaises(InvalidBundleError) as caught:
            metadata.require_platform("ios")
        message = str(caught.exception)
        self.assertIn("ios", message)
        self.assertIn("android", message)


class ExpoConfigTests(OTATestCase):
    def test_reads_expo_config(self):
        config = {"name": "Fitboook", "version": "1.2.2", "extra": {"api": "https://x"}}
        export_dir = make_export_dir(self.tmp_dir, expo_config=config)
        self.assertEqual(load_expo_config(export_dir), config)

    def test_missing_file_returns_empty_dict(self):
        export_dir = make_export_dir(self.tmp_dir)
        self.assertEqual(load_expo_config(export_dir), {})

    def test_malformed_file_returns_empty_dict(self):
        export_dir = make_export_dir(self.tmp_dir)
        (export_dir / "expoConfig.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(load_expo_config(export_dir), {})

    def test_non_object_file_returns_empty_dict(self):
        export_dir = make_export_dir(self.tmp_dir)
        (export_dir / "expoConfig.json").write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(load_expo_config(export_dir), {})

    def test_extra_files_do_not_break_metadata_parsing(self):
        export_dir = make_export_dir(self.tmp_dir)
        add_file(export_dir, "assets/unlisted.bin", b"unlisted")
        metadata = read_export_metadata(export_dir)
        self.assertEqual(len(metadata.require_platform("android").assets), 1)
