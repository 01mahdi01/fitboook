"""JSON admin/CI API: ``/api/admin/updates/...``.

Authentication is either:

* the shared secret ``X-Admin-Key`` header (compared in constant time against
  ``settings.OTA_ADMIN_TOKEN``) — the normal CI path, or
* an authenticated Django staff user session (useful from the browser).

The POST endpoints are ``csrf_exempt`` because CI clients authenticate with the
token header. The session-cookie path is still safe for cross-site POSTs
because Django's default ``SESSION_COOKIE_SAMESITE='Lax'`` prevents the cookie
from being sent on cross-site requests; keep that default (see README security
checklist).
"""

from __future__ import annotations

import functools
import hmac
import json
import logging
from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import conf, services
from .exceptions import InvalidRequest, OTAError, PublishTooLarge
from .http import json_error
from .models import Release, UpdateSettings
from .publishing import publish_from_zip

logger = logging.getLogger(__name__)

ADMIN_KEY_HEADER = "X-Admin-Key"


# ── Authentication ───────────────────────────────────────────────────────────


def _constant_time_equals(expected: str, provided: str) -> bool:
    """Constant-time string comparison (used for the admin token)."""
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def _authorize(request: HttpRequest) -> JsonResponse | None:
    """Return an error response when the request is not authorized, else ``None``."""
    expected = conf.admin_token()
    provided = request.headers.get(ADMIN_KEY_HEADER, "")
    if expected and provided and _constant_time_equals(expected, provided):
        return None

    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_staff:
        return None

    if not expected:
        return json_error(
            "Admin API is disabled: OTA_ADMIN_TOKEN is not configured in Django settings",
            403,
        )
    if not provided:
        return json_error(
            f"Authentication required: send the {ADMIN_KEY_HEADER} header", 401
        )
    return json_error("Invalid admin key", 403)


def admin_endpoint(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Decorator enforcing admin authentication on a view."""

    @functools.wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        denied = _authorize(request)
        if denied is not None:
            return denied
        return view(request, *args, **kwargs)

    return wrapper


# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    text = ("" if value is None else str(value)).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    raise InvalidRequest(f"Invalid boolean value for {field}: {value!r}")


def _parse_json_body(request: HttpRequest) -> dict[str, Any]:
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidRequest(f"Invalid JSON body: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidRequest("JSON body must be an object")
    return data


def _current_user(request: HttpRequest) -> Any:
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return user
    return None


# ── Endpoints ────────────────────────────────────────────────────────────────


@require_GET
@admin_endpoint
def release_list(request: HttpRequest) -> JsonResponse:
    """``GET /api/admin/updates/`` — JSON list of releases, newest first."""
    queryset = Release.objects.select_related("created_by").all()
    runtime_version = (request.GET.get("runtimeVersion") or "").strip()
    platform = (request.GET.get("platform") or "").strip().lower()
    active_raw = request.GET.get("active")

    if runtime_version:
        queryset = queryset.filter(runtime_version=runtime_version)
    if platform:
        queryset = queryset.filter(platform=platform)
    if active_raw is not None:
        try:
            queryset = queryset.filter(
                is_active=_parse_bool(active_raw, field="active")
            )
        except InvalidRequest as exc:
            return json_error(exc.message, exc.status)

    releases = list(queryset[:500])
    latest_cache: dict[tuple[str, str], Release | None] = {}
    payload = []
    for release in releases:
        cache_key = (release.runtime_version, release.platform)
        if cache_key not in latest_cache:
            latest_cache[cache_key] = services.get_latest_release(
                release.runtime_version, release.platform
            )
        latest = latest_cache[cache_key]
        payload.append(
            release.as_dict(is_latest=latest is not None and latest.pk == release.pk)
        )

    return JsonResponse({"count": len(payload), "releases": payload})


@csrf_exempt
@require_POST
@admin_endpoint
def publish(request: HttpRequest) -> JsonResponse:
    """``POST /api/admin/updates/publish/`` — upload a zipped ``expo export`` output."""
    upload = request.FILES.get("bundle")
    runtime_version = (
        request.POST.get("runtimeVersion") or request.POST.get("runtime_version") or ""
    ).strip()
    platform = (request.POST.get("platform") or "").strip()
    notes = request.POST.get("notes") or ""
    activate_raw = request.POST.get("activate")

    if upload is None:
        return json_error(
            "Missing multipart file field 'bundle' (zip containing the `expo export` output)",
            400,
        )

    max_bytes = conf.max_upload_bytes()
    if upload.size is not None and upload.size > max_bytes:
        return json_error(
            f"Uploaded bundle is too large ({upload.size} bytes, max {max_bytes} bytes)",
            413,
        )
    content_length = request.META.get("CONTENT_LENGTH")
    if content_length:
        try:
            if (
                int(content_length) > max_bytes + 1024 * 1024
            ):  # allow multipart overhead
                return json_error("Request body is too large", 413)
        except (TypeError, ValueError):  # pragma: no cover - malformed header
            pass

    try:
        activate = (
            _parse_bool(activate_raw, field="activate")
            if activate_raw is not None
            else True
        )
        result = publish_from_zip(
            upload,
            platform=platform,
            runtime_version=runtime_version,
            notes=notes,
            activate=activate,
            created_by=_current_user(request),
        )
    except PublishTooLarge as exc:
        return json_error(exc.message, 413)
    except OTAError as exc:
        return json_error(exc.message, exc.status)

    release = result.release
    return JsonResponse(
        {
            "ok": True,
            **result.as_dict(),
            "isLatest": services.release_is_latest(release),
        },
        status=201,
    )


@csrf_exempt
@require_POST
@admin_endpoint
def activate(request: HttpRequest, release_id: int) -> JsonResponse:
    """``POST /api/admin/updates/<id>/activate/`` — serve this release again."""
    release = Release.objects.filter(pk=release_id).first()
    if release is None:
        return json_error("Release not found", 404)
    if not release.is_active:
        release.is_active = True
        release.save(update_fields=["is_active"])
    latest = services.get_latest_release(release.runtime_version, release.platform)
    return JsonResponse(
        {
            "ok": True,
            "release": release.as_dict(
                is_latest=latest is not None and latest.pk == release.pk
            ),
            "latestReleaseId": latest.pk if latest is not None else None,
        }
    )


@csrf_exempt
@require_POST
@admin_endpoint
def deactivate(request: HttpRequest, release_id: int) -> JsonResponse:
    """``POST /api/admin/updates/<id>/deactivate/`` — rollback mechanism."""
    release = Release.objects.filter(pk=release_id).first()
    if release is None:
        return json_error("Release not found", 404)
    if release.is_active:
        release.is_active = False
        release.save(update_fields=["is_active"])
    latest = services.get_latest_release(release.runtime_version, release.platform)
    logger.warning(
        "OTA release %s deactivated by %s; latest is now %s",
        release.pk,
        _current_user(request) or "admin token",
        latest.pk if latest is not None else None,
    )
    return JsonResponse(
        {
            "ok": True,
            "release": release.as_dict(is_latest=False),
            "latestReleaseId": latest.pk if latest is not None else None,
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_endpoint
def settings_view(request: HttpRequest) -> JsonResponse:
    """``GET|POST /api/admin/updates/settings/`` — read/toggle the OTA kill switch."""
    settings_row = UpdateSettings.get_solo()

    if request.method == "POST":
        try:
            if request.content_type and "application/json" in request.content_type:
                body = _parse_json_body(request)
                enabled_raw = body.get("enabled")
            else:
                enabled_raw = request.POST.get("enabled")
            if enabled_raw is None:
                raise InvalidRequest("Missing 'enabled' field (true/false)")
            settings_row.enabled = _parse_bool(enabled_raw, field="enabled")
        except OTAError as exc:
            return json_error(exc.message, exc.status)
        settings_row.save(update_fields=["enabled", "updated_at"])
        logger.warning(
            "OTA kill switch set to %s by %s",
            settings_row.enabled,
            _current_user(request) or "admin token",
        )

    return JsonResponse({"ok": True, "settings": settings_row.as_dict()})
