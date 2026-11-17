"""Tests for ``manage.py ota_publish`` and the release workflow it enables."""

from __future__ import annotations

import json
import os
import time
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from ota import services
from ota.metadata import read_export_metadata, update_id_from_metadata_bytes
from ota.models import Release

from .factories import (
    TEST_RUNTIME_VERSION,
    OTATestCase,
    parse_multipart_json,
    parse_multipart_response,
)


def numeric_release_dirs(
    updates_dir: Path, runtime_version: str = TEST_RUNTIME_VERSION
) -> list[Path]:
    runtime_dir = updates_dir / runtime_version
    if not runtime_dir.is_dir():
        return []
    return sorted(
        path for path in runtime_dir.iterdir() if path.is_dir() and path.name.isdigit()
    )


class OtaPublishCommandTests(OTATestCase):
    def call_publish(self, export_dir: Path, **options: object) -> str:
        stdout = StringIO()
        defaults: dict[str, object] = {
            "export_dir": str(export_dir),
            "platform": "android",
            "runtime_version": TEST_RUNTIME_VERSION,
        }
        defaults.update(options)
        call_command("ota_publish", stdout=stdout, **defaults)
        return stdout.getvalue()

    def test_happy_path_publishes_release(self):
        export_dir = self.make_export()
        output = self.call_publish(export_dir, notes="fix login")

        payload = json.loads(output)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["created"])
        self.assertTrue(payload["activated"])
        self.assertRegex(payload["release"]["updateId"], r"^[0-9a-f-]{36}$")

        release = Release.objects.get()
        self.assertEqual(release.runtime_version, TEST_RUNTIME_VERSION)
        self.assertEqual(release.platform, "android")
        self.assertEqual(release.notes, "fix login")
        self.assertTrue(release.is_active)
        self.assertIsNotNone(release.created_at)
        self.assertIsNotNone(release.published_at)
        self.assertEqual(
            release.update_id,
            update_id_from_metadata_bytes((export_dir / "metadata.json").read_bytes()),
        )
        self.assertEqual(payload["release"]["updateId"], release.update_id)

        # Files are copied into the documented layout.
        storage = release.storage_directory
        self.assertEqual(storage.parent.name, TEST_RUNTIME_VERSION)
        self.assertTrue(storage.name.isdigit())
        self.assertEqual(storage.parent.parent, self.updates_dir.resolve())
        self.assertTrue((storage / "metadata.json").is_file())
        self.assertFalse(storage.is_symlink())
        self.assertEqual(len(numeric_release_dirs(self.updates_dir)), 1)

        # ... and the manifest now serves it.
        response = self.client.get(
            "/api/updates/manifest", headers=self.manifest_headers(protocol=1)
        )
        self.assertEqual(
            parse_multipart_json(response, "manifest")["id"], release.update_id
        )

    def test_no_activate_flag_stores_release_inactive(self):
        export_dir = self.make_export()
        payload = json.loads(self.call_publish(export_dir, no_activate=True))

        release = Release.objects.get()
        self.assertFalse(release.is_active)
        self.assertFalse(payload["activated"])
        self.assertIsNone(services.get_latest_release(TEST_RUNTIME_VERSION, "android"))
        response = self.client.get(
            "/api/updates/manifest", headers=self.manifest_headers(protocol=1)
        )
        parts = parse_multipart_response(response)
        self.assertEqual(
            json.loads(parts["directive"].get_payload(decode=True))["type"],
            "noUpdateAvailable",
        )

    def test_second_publish_becomes_latest(self):
        self.call_publish(self.make_export(platform="android"))
        first_release = Release.objects.get()
        self.call_publish(self.make_export(platform="android"))
        second_release = Release.objects.exclude(pk=first_release.pk).get()
        self.assertNotEqual(first_release.update_id, second_release.update_id)
        self.assertEqual(
            services.get_latest_release(TEST_RUNTIME_VERSION, "android").pk,
            second_release.pk,
        )
        self.assertTrue(first_release.is_active)  # rollback candidates stay active

    def test_republishing_same_export_updates_the_row(self):
        export_dir = self.make_export()
        self.call_publish(export_dir)
        first = Release.objects.get()
        first_storage = first.storage_directory
        first_update_id = first.update_id

        self.call_publish(export_dir, notes="same content again")
        self.assertEqual(Release.objects.count(), 1)
        release = Release.objects.get()
        self.assertEqual(release.update_id, first_update_id)
        self.assertEqual(release.notes, "same content again")
        self.assertEqual(len(numeric_release_dirs(self.updates_dir)), 1)
        self.assertFalse(first_storage.exists())  # old copy removed
        self.assertTrue(release.storage_directory.is_dir())

    def test_created_by_option_records_publisher(self):
        user = get_user_model().objects.create_user(**{get_user_model().USERNAME_FIELD: "publisher"}, password="x")
        self.call_publish(self.make_export(), created_by="publisher")
        self.assertEqual(Release.objects.get().created_by_id, user.pk)

    def test_unknown_created_by_is_a_command_error(self):
        with self.assertRaises(CommandError):
            self.call_publish(self.make_export(), created_by="nobody")

    def test_max_releases_option_prunes(self):
        self.call_publish(self.make_export())
        self.call_publish(self.make_export())
        self.call_publish(self.make_export(), max_releases=2)
        self.assertEqual(Release.objects.count(), 2)

    # ── Rejections ───────────────────────────────────────────────────────

    def test_missing_metadata_json_is_rejected(self):
        empty = self.tmp_dir / "empty-export"
        empty.mkdir()
        with self.assertRaises(CommandError) as caught:
            self.call_publish(empty)
        self.assertIn("metadata.json", str(caught.exception))
        self.assertEqual(Release.objects.count(), 0)
        self.assertEqual(numeric_release_dirs(self.updates_dir), [])

    def test_missing_bundle_file_is_rejected(self):
        export_dir = self.make_export()
        metadata = read_export_metadata(export_dir)
        (export_dir / metadata.require_platform("android").bundle).unlink()
        with self.assertRaises(CommandError) as caught:
            self.call_publish(export_dir)
        self.assertIn("missing", str(caught.exception).lower())
        self.assertEqual(Release.objects.count(), 0)
        self.assertEqual(numeric_release_dirs(self.updates_dir), [])

    def test_unsafe_bundle_path_is_rejected(self):
        export_dir = self.make_export()
        document = json.loads(
            (export_dir / "metadata.json").read_text(encoding="utf-8")
        )
        document["fileMetadata"]["android"]["bundle"] = "../../etc/passwd"
        (export_dir / "metadata.json").write_text(
            json.dumps(document), encoding="utf-8"
        )
        with self.assertRaises(CommandError):
            self.call_publish(export_dir)
        self.assertEqual(Release.objects.count(), 0)

    def test_invalid_runtime_version_is_rejected(self):
        with self.assertRaises(CommandError):
            self.call_publish(self.make_export(), runtime_version="../1.2.2")
        self.assertEqual(Release.objects.count(), 0)

    def test_platform_not_in_metadata_is_rejected(self):
        android_export = self.make_export(platform="android")
        with self.assertRaises(CommandError) as caught:
            self.call_publish(android_export, platform="ios")
        self.assertIn("ios", str(caught.exception))
        self.assertEqual(Release.objects.count(), 0)

    def test_nonexistent_export_dir_is_rejected(self):
        with self.assertRaises(CommandError):
            self.call_publish(self.tmp_dir / "nope")

    def test_stale_staging_directories_are_cleaned_up(self):
        runtime_dir = self.updates_dir / TEST_RUNTIME_VERSION
        stale = runtime_dir / ".staging-deadbeef"
        stale.mkdir(parents=True)
        (stale / "metadata.json").write_bytes(b"{}")
        old = time.time() - 2 * 60 * 60
        os.utime(stale, (old, old))
        fresh = runtime_dir / ".staging-fresh"
        fresh.mkdir()

        self.call_publish(self.make_export())

        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())

    def test_failed_publish_leaves_no_staging_garbage(self):
        export_dir = self.make_export()
        (export_dir / "metadata.json").unlink()
        with self.assertRaises(CommandError):
            self.call_publish(export_dir)
        runtime_dir = self.updates_dir / TEST_RUNTIME_VERSION
        if runtime_dir.is_dir():
            leftovers = [path.name for path in runtime_dir.iterdir()]
            self.assertEqual(leftovers, [])
