"""Tests for URL contract, Django admin registration and migration hygiene."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import resolve, reverse

from ota.models import Release, UpdateSettings

from .factories import OTATestCase


class UrlContractTests(SimpleTestCase):
    """The Expo client points at exact URLs; they must never move."""

    def test_client_urls_resolve(self):
        self.assertEqual(resolve("/api/updates/manifest").url_name, "manifest")
        self.assertEqual(resolve("/api/updates/assets").url_name, "assets")
        self.assertEqual(resolve("/api/updates/manifest").app_name, "ota")

    def test_client_urls_reverse(self):
        self.assertEqual(reverse("ota:manifest"), "/api/updates/manifest")
        self.assertEqual(reverse("ota:assets"), "/api/updates/assets")

    def test_trailing_slash_variants_resolve(self):
        self.assertEqual(resolve("/api/updates/manifest/").url_name, "manifest-slash")
        self.assertEqual(resolve("/api/updates/assets/").url_name, "assets-slash")

    def test_admin_api_urls_reverse(self):
        self.assertEqual(reverse("ota_admin:release-list"), "/api/admin/updates/")
        self.assertEqual(reverse("ota_admin:publish"), "/api/admin/updates/publish/")
        self.assertEqual(reverse("ota_admin:settings"), "/api/admin/updates/settings/")
        self.assertEqual(
            reverse("ota_admin:activate", args=[7]), "/api/admin/updates/7/activate/"
        )
        self.assertEqual(
            reverse("ota_admin:deactivate", args=[7]),
            "/api/admin/updates/7/deactivate/",
        )

    def test_admin_api_urls_resolve(self):
        self.assertEqual(resolve("/api/admin/updates/").url_name, "release-list")
        self.assertEqual(resolve("/api/admin/updates/publish/").url_name, "publish")
        self.assertEqual(resolve("/api/admin/updates/settings/").url_name, "settings")


class DjangoAdminTests(OTATestCase):
    def setUp(self) -> None:
        super().setUp()
        self.release = self.publish(notes="admin test").release
        self.admin_user = get_user_model().objects.create_superuser(
            **{get_user_model().USERNAME_FIELD: "admin"}, password="admin-pass-123", email="admin@example.com"
        )
        self.client.force_login(self.admin_user)

    def test_models_are_registered(self):
        self.assertTrue(admin.site.is_registered(Release))
        self.assertTrue(admin.site.is_registered(UpdateSettings))

    def test_release_changelist_renders(self):
        response = self.client.get(reverse("admin:ota_release_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.release.update_id)

    def test_release_change_page_renders(self):
        response = self.client.get(
            reverse("admin:ota_release_change", args=[self.release.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "metadata.json")
        self.assertContains(response, self.release.storage_path)

    def test_settings_change_page_renders(self):
        settings_row = UpdateSettings.get_solo()
        response = self.client.get(
            reverse("admin:ota_updatesettings_change", args=[settings_row.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "kill switch")

    def test_admin_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("admin:ota_release_changelist"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_non_staff_user_cannot_access_admin(self):
        user = get_user_model().objects.create_user(**{get_user_model().USERNAME_FIELD: "plain"}, password="pw")
        self.client.force_login(user)
        response = self.client.get(reverse("admin:ota_release_changelist"))
        self.assertEqual(response.status_code, 302)


class MigrationHygieneTests(TestCase):
    def test_no_model_changes_without_migrations(self):
        try:
            call_command("makemigrations", "ota", "--check", "--dry-run", verbosity=0)
        except SystemExit:  # pragma: no cover - only on a developer mistake
            self.fail(
                "Models changed but no migration was generated. Run "
                "`python manage.py makemigrations ota` and commit the migration file."
            )

    def test_migration_applies_cleanly(self):
        # The test database is created from migrations, so reaching this point
        # already proves the initial migration is valid; assert the table contract.
        self.assertEqual(Release._meta.db_table, "ota_release")
        self.assertEqual(UpdateSettings._meta.db_table, "ota_updatesettings")
        fields = {field.name for field in Release._meta.get_fields()}
        for expected in (
            "runtime_version",
            "platform",
            "update_id",
            "published_at",
            "metadata",
            "storage_path",
            "notes",
            "is_active",
            "created_by",
        ):
            self.assertIn(expected, fields)


class SettingsDefaultsTests(SimpleTestCase):
    def test_ota_settings_are_configured(self):
        from django.conf import settings

        self.assertTrue(hasattr(settings, "OTA_UPDATES_DIR"))
        self.assertTrue(hasattr(settings, "OTA_PUBLIC_BASE_URL"))
        self.assertTrue(hasattr(settings, "OTA_ADMIN_TOKEN"))
        self.assertGreater(settings.OTA_MAX_UPLOAD_BYTES, 0)
        self.assertGreater(settings.OTA_MAX_RELEASES, 0)
