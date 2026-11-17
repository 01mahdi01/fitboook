"""Public Expo Updates protocol endpoints: manifest + assets.

Both endpoints are intentionally unauthenticated: the Expo client fetches them
with no credentials. They only expose published, already-public JS bundles and
the app config that is embedded in the binary anyway.
"""

from __future__ import annotations

import logging

from django.http import FileResponse, HttpRequest, HttpResponse
from django.views.decorators.http import require_GET

from . import services
from .exceptions import (
    InvalidRequest,
    OTAError,
    UnsupportedPlatform,
    UnsupportedProtocolVersion,
)
from .http import (
    IMMUTABLE_CACHE,
    json_error,
    manifest_json_response,
    manifest_multipart_response,
    no_update_directive_response,
)
from .models import PLATFORMS
from .paths import safe_relative_path, validate_runtime_version

logger = logging.getLogger(__name__)

#: Protocol 1 is the modern multipart protocol; protocol 0 is the legacy JSON one.
SUPPORTED_PROTOCOL_VERSIONS = (0, 1)


def parse_protocol_version(request: HttpRequest) -> int:
    """Read ``expo-protocol-version``; missing means legacy protocol 0."""
    raw = request.headers.get("expo-protocol-version")
    if raw is None or not raw.strip():
        return 0
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise InvalidRequest(f"Invalid expo-protocol-version header: {raw!r}") from exc
    if value not in SUPPORTED_PROTOCOL_VERSIONS:
        raise UnsupportedProtocolVersion(
            f"Unsupported expo-protocol-version: {value} (supported: 0, 1)"
        )
    return value


def _request_platform(request: HttpRequest) -> str:
    platform = (
        (request.headers.get("expo-platform") or request.GET.get("platform") or "")
        .strip()
        .lower()
    )
    if platform not in PLATFORMS:
        raise UnsupportedPlatform(
            "Unsupported or missing expo-platform header; expected 'android' or 'ios'"
        )
    return platform


def _request_runtime_version(request: HttpRequest) -> str:
    raw = (
        request.headers.get("expo-runtime-version")
        or request.GET.get("runtime-version")
        or request.GET.get("runtimeVersion")
        or ""
    )
    return validate_runtime_version(raw, field="expo-runtime-version")


@require_GET
def manifest(request: HttpRequest) -> HttpResponse:
    """``GET /api/updates/manifest`` — the latest update for this client."""
    try:
        protocol_version = parse_protocol_version(request)
        platform = _request_platform(request)
        runtime_version = _request_runtime_version(request)
    except OTAError as exc:
        return json_error(exc.message, exc.status)

    if protocol_version == 1:
        if not services.updates_enabled():
            logger.info("OTA kill switch is active; answering noUpdateAvailable")
            return no_update_directive_response()
        release = services.get_latest_release(runtime_version, platform)
        if release is None:
            logger.info(
                "No OTA release for runtimeVersion=%s platform=%s",
                runtime_version,
                platform,
            )
            return no_update_directive_response()
        current_update_id = (
            request.headers.get("expo-current-update-id") or ""
        ).strip()
        if current_update_id and current_update_id == release.update_id:
            return no_update_directive_response()
        try:
            manifest_document, extensions = services.build_manifest(
                release, platform, services.public_base_url(request)
            )
        except OTAError as exc:
            logger.error("Cannot build manifest for release %s: %s", release.pk, exc)
            return json_error(exc.message, 500)
        return manifest_multipart_response(manifest_document, extensions)

    # ── legacy protocol 0: plain JSON manifest or 404 when there is nothing ──
    if not services.updates_enabled():
        return json_error("No update available", 404)
    release = services.get_latest_release(runtime_version, platform)
    if release is None:
        logger.info(
            "No OTA release for runtimeVersion=%s platform=%s (protocol 0)",
            runtime_version,
            platform,
        )
        return json_error("No update available", 404)
    try:
        manifest_document, _extensions = services.build_manifest(
            release, platform, services.public_base_url(request)
        )
    except OTAError as exc:
        logger.error("Cannot build manifest for release %s: %s", release.pk, exc)
        return json_error(exc.message, 500)
    return manifest_json_response(manifest_document)


@require_GET
def asset(request: HttpRequest) -> HttpResponse:
    """``GET /api/updates/assets`` — immutable JS bundle/asset bytes."""
    raw_asset = request.GET.get("asset") or ""
    raw_runtime_version = (
        request.GET.get("runtimeVersion") or request.GET.get("runtime-version") or ""
    )
    raw_platform = (request.GET.get("platform") or "").strip().lower()

    if not raw_asset:
        return json_error("Missing required query parameter: asset", 400)
    if raw_platform not in PLATFORMS:
        return json_error(
            "Unsupported or missing platform; expected 'android' or 'ios'", 400
        )
    try:
        runtime_version = validate_runtime_version(
            raw_runtime_version, field="runtimeVersion"
        )
        asset_path = safe_relative_path(raw_asset, field="asset")
    except OTAError as exc:
        return json_error(exc.message, exc.status)

    try:
        found = services.find_asset(runtime_version, raw_platform, asset_path)
    except OTAError as exc:
        return json_error(exc.message, exc.status)
    if found is None:
        return json_error("Asset not found", 404)

    file_path, content_type = found
    try:
        # FileResponse owns the handle and closes it once streaming completes.
        response = FileResponse(
            open(file_path, "rb"),  # noqa: SIM115 - streamed/closed by FileResponse
            content_type=content_type,
        )
    except OSError:
        logger.warning("Asset disappeared while serving: %s", file_path)
        return json_error("Asset not found", 404)
    response["Cache-Control"] = IMMUTABLE_CACHE
    try:
        response["Content-Length"] = str(file_path.stat().st_size)
    except OSError:  # pragma: no cover - file vanished between open/stat
        pass
    return response
