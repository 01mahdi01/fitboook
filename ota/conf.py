"""Typed accessors for the ``OTA_*`` Django settings.

Settings are read lazily (on every call) instead of being cached at import time
so that ``override_settings`` works in tests and so a settings file can be
changed without restarting the process in development.
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

DEFAULT_MAX_UPLOAD_BYTES = 256 * 1024 * 1024  # 256 MiB
DEFAULT_MAX_RELEASES = 20
DEFAULT_ASSETS_PATH = "/api/updates/assets"


def updates_dir() -> Path:
    """Absolute path of the published bundles root (``OTA_UPDATES_DIR``)."""
    raw = getattr(settings, "OTA_UPDATES_DIR", None)
    if not raw:
        raise ImproperlyConfigured(
            "OTA_UPDATES_DIR is not configured. Add it to your Django settings, e.g. "
            'OTA_UPDATES_DIR = BASE_DIR / "ota-updates"'
        )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        base_dir = getattr(settings, "BASE_DIR", None)
        path = Path(base_dir) / path if base_dir else (Path.cwd() / path)
    return path.resolve()


def public_base_url() -> str:
    """Configured public origin used for asset URLs, without trailing slash."""
    raw = getattr(settings, "OTA_PUBLIC_BASE_URL", "") or ""
    return str(raw).strip().rstrip("/")


def admin_token() -> str:
    """Shared admin/CI token, or an empty string when not configured."""
    return str(getattr(settings, "OTA_ADMIN_TOKEN", "") or "")


def max_upload_bytes() -> int:
    """Maximum accepted size of a zipped publish upload, in bytes."""
    raw = getattr(settings, "OTA_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid OTA_MAX_UPLOAD_BYTES=%r; falling back to default", raw)
        return DEFAULT_MAX_UPLOAD_BYTES
    if value <= 0:
        logger.warning(
            "Non-positive OTA_MAX_UPLOAD_BYTES=%r; falling back to default", raw
        )
        return DEFAULT_MAX_UPLOAD_BYTES
    return value


def max_releases() -> int:
    """How many releases to keep per runtimeVersion (>= 1)."""
    raw = getattr(settings, "OTA_MAX_RELEASES", DEFAULT_MAX_RELEASES)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid OTA_MAX_RELEASES=%r; falling back to default", raw)
        return DEFAULT_MAX_RELEASES
    if value <= 0:
        logger.warning("Non-positive OTA_MAX_RELEASES=%r; falling back to default", raw)
        return DEFAULT_MAX_RELEASES
    return value


def assets_path() -> str:
    """Public URL path of the asset endpoint, always starting with ``/``."""
    raw = str(
        getattr(settings, "OTA_ASSETS_PATH", DEFAULT_ASSETS_PATH) or DEFAULT_ASSETS_PATH
    )
    raw = raw.strip()
    if not raw.startswith("/"):
        raw = "/" + raw
    return raw.rstrip("/") or DEFAULT_ASSETS_PATH
