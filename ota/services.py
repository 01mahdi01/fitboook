"""Business logic: resolve the latest release, build manifests, find assets.

The public HTTP views are intentionally thin; everything protocol-related lives
here so it can be unit-tested without a request object and reused by the
management commands.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from django.http import HttpRequest

from . import conf
from .exceptions import InvalidBundleError, OTAError
from .metadata import (
    AssetRef,
    content_type_for_extension,
    file_digests,
    load_expo_config,
)
from .models import PLATFORMS, Release, UpdateSettings, format_rfc3339
from .paths import safe_join, safe_relative_path

logger = logging.getLogger(__name__)

#: Safety bound when walking candidate releases (newest first).
MAX_RELEASE_CANDIDATES = 500


# ── Kill switch / origin ─────────────────────────────────────────────────────


def updates_enabled() -> bool:
    """True unless an admin flipped the global OTA kill switch off."""
    return UpdateSettings.updates_enabled()


def public_base_url(request: HttpRequest | None = None) -> str:
    """Origin used to build absolute asset URLs.

    ``OTA_PUBLIC_BASE_URL`` wins when configured (required in production behind
    a reverse proxy/HTTPS terminator); otherwise it is derived from the request.
    """
    configured = conf.public_base_url()
    if configured:
        return configured
    if request is None:
        raise InvalidBundleError(
            "OTA_PUBLIC_BASE_URL is not configured and no request is available "
            "to derive the public origin"
        )
    return request.build_absolute_uri("/").rstrip("/")


# ── Release resolution ───────────────────────────────────────────────────────


def get_latest_release(runtime_version: str, platform: str) -> Release | None:
    """Newest *active* release for ``runtime_version`` that serves ``platform``.

    A release only qualifies when its ``metadata.fileMetadata`` contains the
    requested platform and the bundle file is still on disk. Broken rows (e.g.
    files deleted out-of-band) are skipped with a warning so they cannot take
    the whole update channel down.
    """
    if platform not in PLATFORMS:
        return None
    candidates = Release.objects.filter(
        runtime_version=runtime_version, is_active=True
    ).newest_first()[:MAX_RELEASE_CANDIDATES]
    for release in candidates:
        if not release.supports_platform(platform):
            continue
        if not release.files_present(platform):
            logger.warning(
                "Skipping OTA release %s: bundle file missing for platform %s",
                release.pk,
                platform,
            )
            continue
        return release
    return None


def release_is_latest(release: Release) -> bool:
    """Whether ``release`` is the one currently served for its own platform."""
    if release.platform not in PLATFORMS:
        return False
    latest = get_latest_release(release.runtime_version, release.platform)
    return latest is not None and latest.pk == release.pk


def supported_platforms(release: Release) -> list[str]:
    """Platforms contained in a release's metadata."""
    return [platform for platform in PLATFORMS if release.supports_platform(platform)]


# ── Asset URLs ───────────────────────────────────────────────────────────────


def build_asset_url(
    base_url: str,
    asset_path: str,
    runtime_version: str,
    platform: str,
) -> str:
    """Absolute asset URL pointed at ``GET /api/updates/assets``."""
    base = base_url.rstrip("/")
    return (
        f"{base}{conf.assets_path()}"
        f"?asset={quote(asset_path, safe='')}"
        f"&runtimeVersion={quote(runtime_version, safe='')}"
        f"&platform={quote(platform, safe='')}"
    )


# ── Manifest building ────────────────────────────────────────────────────────


def _asset_entry(
    release: Release,
    asset_path: str,
    *,
    ext: str,
    is_launch: bool,
    platform: str,
    base_url: str,
) -> dict[str, Any]:
    """Build one ``Asset`` object for the manifest."""
    asset_path = safe_relative_path(asset_path, field="asset path")
    stored = (
        release.asset_metadata.get(asset_path)
        if isinstance(release.asset_metadata, dict)
        else None
    )

    if isinstance(stored, dict) and stored.get("hash") and stored.get("key"):
        digest = str(stored["hash"])
        key = str(stored["key"])
    else:
        # Fallback for rows created before asset_metadata existed (or repaired DB rows).
        file_path = safe_join(release.storage_directory, asset_path, field="asset path")
        if not file_path.is_file():
            raise InvalidBundleError(f"Release file is missing on disk: {asset_path}")
        digest, key = file_digests(file_path)

    if is_launch:
        content_type = "application/javascript"
        file_extension = ".bundle"
    else:
        content_type = content_type_for_extension(ext)
        ext = ext.strip().lower().lstrip(".")
        file_extension = f".{ext}" if ext else ""

    return {
        "hash": digest,
        "key": key,
        "fileExtension": file_extension,
        "contentType": content_type,
        "url": build_asset_url(base_url, asset_path, release.runtime_version, platform),
    }


def _platform_assets(metadata: dict[str, Any]) -> list[AssetRef]:
    """Extract validated asset refs from a platform metadata dictionary."""
    raw_assets = metadata.get("assets") or []
    if not isinstance(raw_assets, list):
        raise InvalidBundleError("Release metadata is corrupted: assets must be a list")
    assets: list[AssetRef] = []
    for item in raw_assets:
        if not isinstance(item, dict):
            raise InvalidBundleError(
                "Release metadata is corrupted: asset entry must be an object"
            )
        raw_path = item.get("path")
        if not isinstance(raw_path, str):
            raise InvalidBundleError(
                "Release metadata is corrupted: asset path is missing"
            )
        ext = item.get("ext") if isinstance(item.get("ext"), str) else ""
        assets.append(
            AssetRef(path=safe_relative_path(raw_path, field="asset path"), ext=ext)
        )
    return assets


def build_manifest(
    release: Release,
    platform: str,
    base_url: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(manifest, extensions)`` for a release/platform pair."""
    if platform not in PLATFORMS:
        raise InvalidBundleError(f"Unsupported platform: {platform!r}")
    metadata = release.platform_metadata(platform)
    if metadata is None:
        raise InvalidBundleError(
            f"Release {release.pk} has no metadata for platform {platform!r}"
        )
    raw_bundle = metadata.get("bundle")
    if not isinstance(raw_bundle, str) or not raw_bundle:
        raise InvalidBundleError(
            f"Release {release.pk} has no bundle path for {platform!r}"
        )

    bundle_path = safe_relative_path(raw_bundle, field="bundle path")
    launch_asset = _asset_entry(
        release,
        bundle_path,
        ext="",
        is_launch=True,
        platform=platform,
        base_url=base_url,
    )
    assets = [
        _asset_entry(
            release,
            asset.path,
            ext=asset.ext,
            is_launch=False,
            platform=platform,
            base_url=base_url,
        )
        for asset in _platform_assets(metadata)
    ]

    manifest: dict[str, Any] = {
        "id": release.update_id,
        "createdAt": format_rfc3339(release.published_at),
        "runtimeVersion": release.runtime_version,
        "launchAsset": launch_asset,
        "assets": assets,
        "metadata": {},
        "extra": {"expoClient": load_expo_config(release.storage_directory)},
    }

    # No custom CDN headers are needed, but the key must be present for every
    # asset (including the launch bundle) so the client knows there is nothing
    # extra to send when downloading.
    asset_request_headers = {entry["key"]: {} for entry in (launch_asset, *assets)}
    extensions = {"assetRequestHeaders": asset_request_headers}
    return manifest, extensions


# ── Asset resolution ─────────────────────────────────────────────────────────


def _content_type_for_path(
    release: Release, platform: str, asset_path: str
) -> str | None:
    """Content type if ``asset_path`` is declared in the release, else ``None``."""
    metadata = release.platform_metadata(platform)
    if metadata is None:
        return None
    raw_bundle = metadata.get("bundle")
    if isinstance(raw_bundle, str):
        try:
            if safe_relative_path(raw_bundle, field="bundle path") == asset_path:
                return "application/javascript"
        except (OTAError, OSError, ValueError):
            pass
    for item in metadata.get("assets") or []:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        try:
            path = safe_relative_path(item["path"], field="asset path")
        except (OTAError, OSError, ValueError):
            continue
        if path == asset_path:
            ext = item.get("ext") if isinstance(item.get("ext"), str) else ""
            return content_type_for_extension(ext)
    return None


def find_asset(
    runtime_version: str,
    platform: str,
    asset_path: str,
) -> tuple[Path, str] | None:
    """Locate an asset file and its content type.

    Assets must stay downloadable even after a rollback and even when the kill
    switch is off (clients that already downloaded an update keep requesting
    files). Therefore *all* releases for the runtimeVersion are searched,
    newest first, instead of only the currently served one. Expo export gives
    every file a content-hashed name, so the newest matching release wins
    without ambiguity for real bundles.
    """
    if platform not in PLATFORMS:
        return None
    relative = safe_relative_path(asset_path, field="asset")
    candidates = Release.objects.filter(runtime_version=runtime_version).newest_first()[
        :MAX_RELEASE_CANDIDATES
    ]
    for release in candidates:
        content_type = _content_type_for_path(release, platform, relative)
        if content_type is None:
            continue
        try:
            file_path = safe_join(release.storage_directory, relative, field="asset")
        except (OTAError, OSError, ValueError):
            continue
        if file_path.is_file():
            return file_path, content_type
    return None
