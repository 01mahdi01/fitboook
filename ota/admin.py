"""Django admin integration for OTA releases and the kill switch."""

from __future__ import annotations

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from . import services
from .models import Release, UpdateSettings


@admin.register(Release)
class ReleaseAdmin(admin.ModelAdmin):
    """Read-only-ish view of published releases with activate/deactivate actions.

    Releases are normally created by ``manage.py ota_publish`` or the CI publish
    endpoint; the admin is for auditing, rollback and re-activation.
    """

    list_display = (
        "update_id",
        "runtime_version",
        "platform",
        "is_active",
        "is_latest_badge",
        "published_at",
        "created_by",
    )
    list_filter = ("platform", "is_active", "runtime_version")
    search_fields = ("update_id", "runtime_version", "notes", "storage_path")
    date_hierarchy = "published_at"
    ordering = ("-published_at", "-id")
    readonly_fields = (
        "update_id",
        "runtime_version",
        "platform",
        "created_at",
        "published_at",
        "storage_path",
        "metadata_preview",
        "asset_metadata",
        "created_by",
    )
    actions = ("mark_active", "mark_inactive")
    list_per_page = 50

    @admin.display(description="latest")
    def is_latest_badge(self, obj: Release) -> str | bool:
        if services.release_is_latest(obj):
            return format_html('<span style="color:#0a7d32;font-weight:600">●</span>')
        return ""

    @admin.display(description="metadata.json")
    def metadata_preview(self, obj: Release) -> str:
        file_metadata = (obj.metadata or {}).get("fileMetadata", {})
        platforms = (
            ", ".join(sorted(file_metadata)) if isinstance(file_metadata, dict) else "?"
        )
        return f"version={obj.metadata.get('version', '?')}, bundler={obj.metadata.get('bundler', '?')}, platforms: {platforms}"

    @admin.action(description="Activate selected releases")
    def mark_active(self, request: HttpRequest, queryset: QuerySet[Release]) -> None:
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} release(s) activated.", messages.SUCCESS)

    @admin.action(description="Deactivate selected releases (rollback)")
    def mark_inactive(self, request: HttpRequest, queryset: QuerySet[Release]) -> None:
        updated = queryset.update(is_active=False)
        self.message_user(
            request, f"{updated} release(s) deactivated.", messages.WARNING
        )

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Releases must go through the publish pipeline so files+DB stay in sync.
        return False


@admin.register(UpdateSettings)
class UpdateSettingsAdmin(admin.ModelAdmin):
    """Singleton kill-switch editor (one row, no add/delete)."""

    list_display = ("__str__", "enabled", "updated_at")
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return not UpdateSettings.objects.exists()

    def has_delete_permission(
        self, request: HttpRequest, obj: UpdateSettings | None = None
    ) -> bool:
        return False
