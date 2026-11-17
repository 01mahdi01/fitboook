"""Tests for the retention window (OTA_MAX_RELEASES pruning)."""

from __future__ import annotations

from ota.models import Release
from ota.publishing import prune_releases

from .factories import TEST_RUNTIME_VERSION, OTATestCase, make_export_dir


class RetentionTests(OTATestCase):
    def test_oldest_releases_are_pruned_after_publish(self):
        with self.settings(OTA_MAX_RELEASES=3):
            releases = [self.publish().release for _ in range(5)]

        self.assertEqual(Release.objects.count(), 3)
        remaining_ids = set(Release.objects.values_list("pk", flat=True))
        newest_three = {release.pk for release in releases[2:]}
        self.assertEqual(remaining_ids, newest_three)
        numeric_dirs = {
            path.name
            for path in (self.updates_dir / TEST_RUNTIME_VERSION).iterdir()
            if path.is_dir() and path.name.isdigit()
        }
        most_recent = releases[-1].storage_directory.name
        self.assertIn(most_recent, numeric_dirs)
        for pruned in releases[:2]:
            self.assertFalse(pruned.storage_directory.exists())
        self.assertEqual(len(numeric_dirs), 3)

    def test_pruning_is_per_runtime_version(self):
        with self.settings(OTA_MAX_RELEASES=2):
            for _ in range(3):
                self.publish(runtime_version="1.2.2")
            for _ in range(3):
                self.publish(runtime_version="1.2.3")
        self.assertEqual(Release.objects.filter(runtime_version="1.2.2").count(), 2)
        self.assertEqual(Release.objects.filter(runtime_version="1.2.3").count(), 2)

    def test_no_pruning_below_limit(self):
        with self.settings(OTA_MAX_RELEASES=10):
            self.publish()
            self.publish()
        self.assertEqual(Release.objects.count(), 2)

    def test_prune_does_not_delete_files_still_referenced(self):
        first = self.publish().release
        second = self.publish().release
        third = self.publish().release

        # Simulate a row that shares the oldest release's storage directory
        # (e.g. a manual dual-platform row) - the files must survive pruning.
        Release.objects.create(
            runtime_version=TEST_RUNTIME_VERSION,
            platform="ios",
            update_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            metadata=first.metadata,
            storage_path=first.storage_path,
        )
        deleted = prune_releases(TEST_RUNTIME_VERSION, max_releases=2)
        self.assertIn(first.pk, deleted)
        self.assertIn(second.pk, deleted)
        # The oldest row was deleted but its files are still referenced by the
        # shared ios row, so they must NOT be removed.
        self.assertTrue(first.storage_directory.exists())
        self.assertFalse(second.storage_directory.exists())
        self.assertEqual(Release.objects.count(), 2)  # third + shared ios row
        del third

    def test_prune_releases_accepts_explicit_limit(self):
        for _ in range(4):
            self.publish()
        deleted = prune_releases(TEST_RUNTIME_VERSION, max_releases=1)
        self.assertEqual(Release.objects.count(), 1)
        self.assertEqual(len(deleted), 3)

    def test_default_retention_is_twenty(self):
        for _ in range(22):
            self.publish()
        self.assertEqual(Release.objects.count(), 20)

    def test_command_max_releases_override_wins_over_settings(self):
        from io import StringIO

        from django.core.management import call_command

        with self.settings(OTA_MAX_RELEASES=10):
            for _ in range(3):
                call_command(
                    "ota_publish",
                    export_dir=str(make_export_dir(self.tmp_dir)),
                    platform="android",
                    runtime_version=TEST_RUNTIME_VERSION,
                    max_releases=2,
                    stdout=StringIO(),
                )
        self.assertEqual(Release.objects.count(), 2)
