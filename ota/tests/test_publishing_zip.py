"""Tests for the zip-based publishing pipeline (CI upload path)."""

from __future__ import annotations

import io
import warnings
import zipfile
from unittest import mock

from ota.exceptions import InvalidArchive, InvalidBundleError, PublishTooLarge
from ota.models import Release
from ota.publishing import publish_from_zip

from .factories import (
    TEST_RUNTIME_VERSION,
    OTATestCase,
    make_export_dir,
    make_symlink_zip,
    make_zip,
)


class PublishFromZipTests(OTATestCase):
    def test_publishes_zip_of_export_content(self):
        export_dir = make_export_dir(self.tmp_dir)
        archive = make_zip(export_dir)

        result = publish_from_zip(
            archive,
            platform="android",
            runtime_version=TEST_RUNTIME_VERSION,
            notes="from ci",
        )

        self.assertTrue(result.created)
        release = result.release
        self.assertTrue(release.is_active)
        self.assertEqual(release.notes, "from ci")
        self.assertTrue((release.storage_directory / "metadata.json").is_file())
        self.assertTrue(release.asset_metadata)
        self.assertEqual(release.storage_directory.parent.name, TEST_RUNTIME_VERSION)

    def test_zip_with_single_top_level_folder_is_accepted(self):
        export_dir = make_export_dir(self.tmp_dir)
        archive = make_zip(export_dir, top_level_folder="dist-ota")

        result = publish_from_zip(
            archive, platform="android", runtime_version=TEST_RUNTIME_VERSION
        )
        self.assertTrue(result.created)

    def test_invalid_zip_is_rejected(self):
        with self.assertRaises(InvalidArchive):
            publish_from_zip(
                b"this is definitely not a zip file",
                platform="android",
                runtime_version=TEST_RUNTIME_VERSION,
            )
        self.assertEqual(Release.objects.count(), 0)

    def test_empty_zip_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w"):
            pass
        with self.assertRaises(InvalidArchive):
            publish_from_zip(
                buffer.getvalue(),
                platform="android",
                runtime_version=TEST_RUNTIME_VERSION,
            )

    def test_zip_slip_is_rejected(self):
        export_dir = make_export_dir(self.tmp_dir)
        archive = make_zip(export_dir, extra_entries={"../evil.txt": b"pwned"})

        with self.assertRaises(InvalidArchive) as caught:
            publish_from_zip(
                archive, platform="android", runtime_version=TEST_RUNTIME_VERSION
            )
        self.assertIn("traversal", str(caught.exception).lower())
        self.assertFalse((self.tmp_dir / "evil.txt").exists())
        self.assertEqual(Release.objects.count(), 0)

    def test_absolute_zip_entry_is_rejected(self):
        export_dir = make_export_dir(self.tmp_dir)
        archive = make_zip(export_dir, extra_entries={"/etc/evil.txt": b"pwned"})
        with self.assertRaises(InvalidArchive):
            publish_from_zip(
                archive, platform="android", runtime_version=TEST_RUNTIME_VERSION
            )

    def test_symlink_zip_entry_is_rejected(self):
        with self.assertRaises(InvalidArchive) as caught:
            publish_from_zip(
                make_symlink_zip(),
                platform="android",
                runtime_version=TEST_RUNTIME_VERSION,
            )
        self.assertIn("ymlink", str(caught.exception))

    def test_duplicate_zip_entries_are_rejected(self):
        export_dir = make_export_dir(self.tmp_dir)
        archive_bytes = make_zip(export_dir)
        # Re-write the same archive appending a duplicate entry name.
        buffer = io.BytesIO(archive_bytes)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # duplicate-name warning
            with zipfile.ZipFile(buffer, "a") as archive:
                archive.writestr("metadata.json", b"{}")
        with self.assertRaises(InvalidArchive) as caught:
            publish_from_zip(
                buffer.getvalue(),
                platform="android",
                runtime_version=TEST_RUNTIME_VERSION,
            )
        self.assertIn("Duplicate", str(caught.exception))

    def test_too_many_zip_entries_are_rejected(self):
        export_dir = make_export_dir(self.tmp_dir)
        archive = make_zip(export_dir)
        with (
            mock.patch("ota.publishing.MAX_ZIP_ENTRIES", 1),
            self.assertRaises(InvalidArchive) as caught,
        ):
            publish_from_zip(
                archive, platform="android", runtime_version=TEST_RUNTIME_VERSION
            )
        self.assertIn("too many entries", str(caught.exception))

    def test_oversized_archive_is_rejected(self):
        with (
            self.settings(OTA_MAX_UPLOAD_BYTES=512),
            self.assertRaises(PublishTooLarge),
        ):
            publish_from_zip(
                b"x" * 1024,
                platform="android",
                runtime_version=TEST_RUNTIME_VERSION,
            )
        self.assertEqual(Release.objects.count(), 0)

    def test_uncompressed_zip_bomb_is_rejected(self):
        export_dir = make_export_dir(
            self.tmp_dir, bundle_bytes=b"a" * 200_000, assets=[]
        )
        archive = make_zip(export_dir)
        self.assertLess(len(archive), 5_000)  # compresses extremely well
        with (
            self.settings(OTA_MAX_UPLOAD_BYTES=10_000),
            self.assertRaises(PublishTooLarge),
        ):
            publish_from_zip(
                archive, platform="android", runtime_version=TEST_RUNTIME_VERSION
            )
        self.assertEqual(Release.objects.count(), 0)

    def test_zip_without_metadata_json_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("readme.txt", b"hello")
        with self.assertRaises(InvalidBundleError):
            publish_from_zip(
                buffer.getvalue(),
                platform="android",
                runtime_version=TEST_RUNTIME_VERSION,
            )
        self.assertEqual(Release.objects.count(), 0)

    def test_failed_upload_cleans_up_staging(self):
        export_dir = make_export_dir(self.tmp_dir)
        archive = make_zip(export_dir, extra_entries={"../evil.txt": b"x"})
        with self.assertRaises(InvalidArchive):
            publish_from_zip(
                archive, platform="android", runtime_version=TEST_RUNTIME_VERSION
            )
        incoming = self.updates_dir / ".incoming"
        if incoming.is_dir():
            self.assertEqual(list(incoming.iterdir()), [])
        runtime_dir = self.updates_dir / TEST_RUNTIME_VERSION
        if runtime_dir.is_dir():
            self.assertEqual(
                [p.name for p in runtime_dir.iterdir() if p.name.isdigit()], []
            )

    def test_zip_upload_supports_activate_false(self):
        export_dir = make_export_dir(self.tmp_dir)
        archive = make_zip(export_dir)
        result = publish_from_zip(
            archive,
            platform="android",
            runtime_version=TEST_RUNTIME_VERSION,
            activate=False,
        )
        self.assertFalse(result.release.is_active)
