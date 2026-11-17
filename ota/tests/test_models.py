"""Model-level tests: release state, rollback semantics, singleton settings."""

from __future__ import annotations

from datetime import UTC, datetime

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase

from ota import services
from ota.models import Release, UpdateSettings, format_rfc3339

from .factories import TEST_RUNTIME_VERSION, OTATestCase


class Rfc3339Tests(SimpleTestCase):
    def test_aware_datetime_is_rendered_in_utc(self):
        value = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        self.assertEqual(format_rfc3339(value), "2026-01-02T03:04:05Z")

    def test_naive_datetime_is_treated_as_utc(self):
        self.assertEqual(
            format_rfc3339(datetime(2026, 1, 2, 3, 4, 5)), "2026-01-02T03:04:05Z"
        )

    def test_none_is_rendered_as_empty_string(self):
        self.assertEqual(format_rfc3339(None), "")


class ReleaseModelTests(OTATestCase):
    def setUp(self) -> None:
        super().setUp()
        self.result = self.publish(notes="first release")
        self.release = self.result.release

    def test_publish_creates_active_release_with_expected_fields(self):
        release = self.release
        self.assertTrue(self.result.created)
        self.assertTrue(release.is_active)
        self.assertEqual(release.runtime_version, TEST_RUNTIME_VERSION)
        self.assertEqual(release.platform, "android")
        self.assertEqual(release.notes, "first release")
        self.assertIsNotNone(release.published_at)
        self.assertIsNotNone(release.created_at)
        self.assertIsNone(release.created_by)
        self.assertEqual(release.metadata["version"], 0)
        self.assertIn("fileMetadata", release.metadata)
        self.assertTrue(release.asset_metadata)

    def test_storage_directory_exists_and_has_files(self):
        release = self.release
        directory = release.storage_directory
        self.assertTrue(directory.is_dir())
        self.assertTrue((directory / "metadata.json").is_file())
        self.assertEqual(directory.name.isdigit(), True)
        self.assertTrue(release.storage_path.startswith(f"{TEST_RUNTIME_VERSION}/"))

    def test_supports_platform_and_files_present(self):
        self.assertTrue(self.release.supports_platform("android"))
        self.assertFalse(self.release.supports_platform("ios"))
        self.assertTrue(self.release.files_present("android"))
        self.assertFalse(self.release.files_present("ios"))
        self.assertEqual(services.supported_platforms(self.release), ["android"])

    def test_platform_metadata_returns_dict(self):
        metadata = self.release.platform_metadata("android")
        self.assertIsInstance(metadata, dict)
        self.assertIn("bundle", metadata)
        self.assertIsNone(self.release.platform_metadata("ios"))

    def test_as_dict_shape(self):
        payload = self.release.as_dict(is_latest=True)
        self.assertEqual(payload["runtimeVersion"], TEST_RUNTIME_VERSION)
        self.assertEqual(payload["platform"], "android")
        self.assertEqual(payload["updateId"], self.release.update_id)
        self.assertTrue(payload["active"])
        self.assertTrue(payload["isLatest"])
        self.assertTrue(payload["publishedAt"].endswith("Z"))
        self.assertIn("storagePath", payload)

    def test_unique_constraint_per_runtime_platform_update(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Release.objects.create(
                runtime_version=self.release.runtime_version,
                platform=self.release.platform,
                update_id=self.release.update_id,
                metadata={},
                storage_path="1.2.2/0000000000000",
            )

    def test_same_update_id_on_other_platform_is_allowed(self):
        duplicate_id_on_ios = Release.objects.create(
            runtime_version=self.release.runtime_version,
            platform="ios",
            update_id=self.release.update_id,
            metadata=self.release.metadata,
            storage_path=self.release.storage_path,
        )
        self.assertIsNotNone(duplicate_id_on_ios.pk)

    def test_release_is_latest(self):
        self.assertTrue(services.release_is_latest(self.release))
        self.release.is_active = False
        self.release.save(update_fields=["is_active"])
        self.assertFalse(services.release_is_latest(self.release))
        self.assertIsNone(services.get_latest_release(TEST_RUNTIME_VERSION, "android"))


class LatestReleaseTests(OTATestCase):
    def test_newest_active_release_wins(self):
        first = self.publish(notes="one").release
        second = self.publish(notes="two").release
        latest = services.get_latest_release(TEST_RUNTIME_VERSION, "android")
        self.assertIsNotNone(latest)
        self.assertEqual(latest.pk, second.pk)
        self.assertNotEqual(first.update_id, second.update_id)

    def test_inactive_newest_falls_back_to_previous(self):
        first = self.publish(notes="one").release
        second = self.publish(notes="two").release
        second.is_active = False
        second.save(update_fields=["is_active"])
        latest = services.get_latest_release(TEST_RUNTIME_VERSION, "android")
        self.assertEqual(latest.pk, first.pk)

    def test_platform_filtering_uses_metadata(self):
        # An android-only release must not be served to iOS clients.
        self.publish(platform="android")
        self.assertIsNone(services.get_latest_release(TEST_RUNTIME_VERSION, "ios"))

    def test_broken_release_is_skipped(self):
        first = self.publish(notes="one").release
        second = self.publish(notes="two").release
        # Simulate retention/ops deleting the newest release files out of band.
        import shutil

        shutil.rmtree(second.storage_directory)
        latest = services.get_latest_release(TEST_RUNTIME_VERSION, "android")
        self.assertEqual(latest.pk, first.pk)

    def test_release_with_corrupt_metadata_path_is_skipped(self):
        first = self.publish(notes="valid").release
        broken = self.publish(notes="broken").release
        broken.metadata = {
            "version": 0,
            "fileMetadata": {"android": {"bundle": "../../etc/passwd", "assets": []}},
        }
        broken.save(update_fields=["metadata"])
        # The broken newest row must be skipped instead of raising (500).
        self.assertFalse(broken.files_present("android"))
        latest = services.get_latest_release(TEST_RUNTIME_VERSION, "android")
        self.assertEqual(latest.pk, first.pk)

    def test_storage_directory_rejects_tampered_path(self):
        from ota.exceptions import UnsafePathError

        release = self.publish().release
        release.storage_path = "../../etc"
        with self.assertRaises(UnsafePathError):
            _ = release.storage_directory

    def test_runtime_versions_are_isolated(self):
        old = self.publish(runtime_version="1.2.2").release
        new = self.publish(runtime_version="1.2.3").release
        self.assertEqual(
            services.get_latest_release("1.2.2", "android").pk,
            old.pk,
        )
        self.assertEqual(
            services.get_latest_release("1.2.3", "android").pk,
            new.pk,
        )


class UpdateSettingsTests(OTATestCase):
    def test_get_solo_is_a_singleton(self):
        first = UpdateSettings.get_solo()
        second = UpdateSettings.get_solo()
        self.assertEqual(first.pk, 1)
        self.assertEqual(second.pk, 1)
        self.assertEqual(UpdateSettings.objects.count(), 1)
        self.assertTrue(first.enabled)

    def test_save_always_reuses_pk_1(self):
        row = UpdateSettings.get_solo()
        row.enabled = False
        row.save()
        self.assertEqual(UpdateSettings.objects.count(), 1)
        self.assertFalse(UpdateSettings.get_solo().enabled)

    def test_updates_enabled_reflects_kill_switch(self):
        self.assertTrue(UpdateSettings.updates_enabled())
        UpdateSettings.objects.filter(pk=1).update(enabled=False)
        self.assertFalse(UpdateSettings.updates_enabled())

    def test_as_dict_shape(self):
        payload = UpdateSettings.get_solo().as_dict()
        self.assertIs(payload["enabled"], True)
        self.assertIn("updatedAt", payload)
