"""Database models for OTA releases and the global kill switch."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone

from . import conf
from .exceptions import OTAError
from .paths import ensure_within, safe_join

logger = logging.getLogger(__name__)

PLATFORM_ANDROID = "android"
PLATFORM_IOS = "ios"
PLATFORM_CHOICES = (
    (PLATFORM_ANDROID, "Android"),
    (PLATFORM_IOS, "iOS"),
)
PLATFORMS = tuple(value for value, _label in PLATFORM_CHOICES)


def format_rfc3339(value: datetime | None) -> str:
    """Format a datetime as RFC 3339 in UTC (e.g. ``2026-01-02T03:04:05Z``)."""
    if value is None:
        return ""
    if timezone.is_naive(value):
        value = timezone.make_aware(value, UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ReleaseQuerySet(models.QuerySet["Release"]):
    """Reusable filters/orderings for releases."""

    def for_runtime_version(self, runtime_version: str) -> ReleaseQuerySet:
        return self.filter(runtime_version=runtime_version)

    def active(self) -> ReleaseQuerySet:
        return self.filter(is_active=True)

    def newest_first(self) -> ReleaseQuerySet:
        return self.order_by("-published_at", "-id")


class ReleaseManager(models.Manager.from_queryset(ReleaseQuerySet)):  # type: ignore[misc]
    """Default manager for :class:`Release`."""


class Release(models.Model):
    """One published OTA update (a snapshot of an ``expo export`` directory).

    A release row is created per platform. The on-disk layout is shared per
    runtimeVersion::

        <OTA_UPDATES_DIR>/<runtime_version>/<timestampMillis>/metadata.json
        <OTA_UPDATES_DIR>/<runtime_version>/<timestampMillis>/expoConfig.json
        <OTA_UPDATES_DIR>/<runtime_version>/<timestampMillis>/_expo/static/js/...
        <OTA_UPDATES_DIR>/<runtime_version>/<timestampMillis>/assets/...

    "Latest update" is resolved by looking at *active* rows for the requested
    runtimeVersion, newest first, and picking the first row whose
    ``metadata.fileMetadata`` contains the requested platform (and whose files
    are still present on disk). ``is_active=False`` is therefore the rollback
    mechanism: deactivating the newest release makes the previous one latest
    again.
    """

    runtime_version = models.CharField(
        max_length=128,
        db_index=True,
        help_text="Must exactly match the runtimeVersion compiled into the app binary.",
    )
    platform = models.CharField(max_length=16, choices=PLATFORM_CHOICES, db_index=True)
    update_id = models.CharField(
        max_length=36,
        help_text="UUID-shaped id derived from sha256(metadata.json) (Expo manifest id).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(default=timezone.now, db_index=True)
    metadata = models.JSONField(
        default=dict,
        help_text="Parsed metadata.json (fileMetadata for each platform).",
    )
    asset_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="rel_path -> {hash, key, content_type} computed at publish time.",
    )
    storage_path = models.CharField(
        max_length=255,
        help_text="Directory relative to OTA_UPDATES_DIR, e.g. '1.2.2/1731000000000'.",
    )
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Deactivate to roll back to the previous active release.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ota_releases",
    )

    objects = ReleaseManager()

    class Meta:
        verbose_name = "OTA release"
        verbose_name_plural = "OTA releases"
        ordering = ("-published_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=["runtime_version", "platform", "update_id"],
                name="ota_release_unique_runtime_platform_update",
            )
        ]
        indexes = [
            models.Index(
                fields=["runtime_version", "is_active", "-published_at"],
                name="ota_release_lookup_idx",
            ),
            models.Index(fields=["storage_path"], name="ota_release_storage_idx"),
        ]

    def __str__(self) -> str:
        state = "active" if self.is_active else "inactive"
        return f"{self.runtime_version} / {self.platform} / {self.update_id} ({state})"

    # ── Filesystem helpers ───────────────────────────────────────────────

    @property
    def storage_directory(self) -> Path:
        """Absolute directory of this release's files.

        Raises :class:`~ota.exceptions.UnsafePathError` if the DB row was
        tampered with and points outside ``OTA_UPDATES_DIR``.
        """
        root = conf.updates_dir()
        return ensure_within(root, root / self.storage_path)

    def platform_metadata(self, platform: str) -> dict[str, Any] | None:
        """Return ``fileMetadata[platform]`` (bundle + assets) or ``None``."""
        if not isinstance(self.metadata, dict):
            return None
        file_metadata = self.metadata.get("fileMetadata")
        if not isinstance(file_metadata, dict):
            return None
        value = file_metadata.get(platform)
        return value if isinstance(value, dict) else None

    def supports_platform(self, platform: str) -> bool:
        """True when this release carries a bundle for ``platform``."""
        metadata = self.platform_metadata(platform)
        return bool(
            metadata and isinstance(metadata.get("bundle"), str) and metadata["bundle"]
        )

    def files_present(self, platform: str) -> bool:
        """True when the platform bundle still exists on disk (retention safety)."""
        metadata = self.platform_metadata(platform)
        if not metadata or not isinstance(metadata.get("bundle"), str):
            return False
        try:
            bundle_path = safe_join(
                self.storage_directory, metadata["bundle"], field="bundle"
            )
        except (OSError, OTAError, ValueError):
            return False
        return bundle_path.is_file()

    # ── Serialization ────────────────────────────────────────────────────

    def as_dict(self, *, is_latest: bool | None = None) -> dict[str, Any]:
        """JSON-friendly representation used by the admin API."""
        data: dict[str, Any] = {
            "id": self.pk,
            "runtimeVersion": self.runtime_version,
            "platform": self.platform,
            "updateId": self.update_id,
            "publishedAt": format_rfc3339(self.published_at),
            "createdAt": format_rfc3339(self.created_at),
            "active": self.is_active,
            "storagePath": self.storage_path,
            "notes": self.notes,
            "createdBy": self.created_by.get_username() if self.created_by_id else None,
        }
        if is_latest is not None:
            data["isLatest"] = is_latest
        return data


class UpdateSettings(models.Model):
    """Singleton row holding the global OTA kill switch.

    ``enabled=False`` makes ``/api/updates/manifest`` answer "no update
    available" for every client, while already published assets stay
    downloadable (clients that already downloaded an update keep working).
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(
        default=True,
        help_text="When off, clients are told no update is available (kill switch).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "OTA settings"
        verbose_name_plural = "OTA settings"

    def __str__(self) -> str:
        return f"OTA {'enabled' if self.enabled else 'DISABLED'}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Enforce a single row; the table is a key/value singleton.
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any):  # pragma: no cover - defensive
        raise NotImplementedError("UpdateSettings is a singleton and cannot be deleted")

    @classmethod
    def get_solo(cls) -> UpdateSettings:
        """Return the singleton row, creating it (enabled) on first use."""
        settings_row, _created = cls.objects.get_or_create(pk=1)
        return settings_row

    @classmethod
    def updates_enabled(cls) -> bool:
        """Kill-switch state. Fails open (enabled) only if the DB read succeeds."""
        return cls.get_solo().enabled

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "updatedAt": format_rfc3339(self.updated_at),
        }
