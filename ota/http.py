"""Tiny HTTP helpers for the Expo Updates protocol.

The protocol has two response encodings:

* protocol 1 (modern clients) — ``multipart/mixed`` with ``manifest`` /
  ``extensions`` / ``directive`` parts,
* protocol 0 (legacy clients) — a plain ``application/json`` manifest.

We build the multipart body by hand (CRLF + boundary exactly as RFC 2046
requires) instead of using a MIME library so the wire format is explicit and
easy to unit test.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

from django.http import HttpRequest, HttpResponse, JsonResponse

#: A multipart part: (part name, content type, raw body bytes).
Part = tuple[str, str, bytes]

#: Common response headers required by the Expo Updates v1 spec.
PROTOCOL_HEADERS = {
    "expo-protocol-version": "1",
    "expo-sfv-version": "0",
}
#: The manifest must never be cached by intermediaries (spec recommendation).
NO_CACHE = "private, max-age=0"
#: Assets are immutable and may be cached forever (spec recommendation).
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"

NO_UPDATE_DIRECTIVE: dict[str, str] = {"type": "noUpdateAvailable"}


def encode_multipart_mixed(parts: Sequence[Part], boundary: str) -> bytes:
    """Encode parts as a ``multipart/mixed`` body (RFC 2046, CRLF line endings)."""
    if not boundary:
        raise ValueError("A multipart boundary is required")
    out = bytearray()
    boundary_bytes = boundary.encode("ascii")
    for name, content_type, body in parts:
        out += b"--" + boundary_bytes + b"\r\n"
        out += (
            b'Content-Disposition: form-data; name="' + name.encode("ascii") + b'"\r\n'
        )
        out += b"Content-Type: " + content_type.encode("ascii") + b"\r\n"
        out += b"\r\n"
        out += body
        out += b"\r\n"
    out += b"--" + boundary_bytes + b"--\r\n"
    return bytes(out)


def build_multipart_response(parts: Sequence[Part]) -> HttpResponse:
    """200 response with the standard Expo protocol headers and multipart body."""
    boundary = f"ota-{uuid.uuid4().hex}"
    body = encode_multipart_mixed(parts, boundary)
    response = HttpResponse(body, content_type=f"multipart/mixed; boundary={boundary}")
    for key, value in PROTOCOL_HEADERS.items():
        response[key] = value
    response["Cache-Control"] = NO_CACHE
    return response


def directive_response(directive: dict[str, object] | None = None) -> HttpResponse:
    """Multipart response carrying a single ``directive`` part (e.g. no update)."""
    payload = directive if directive is not None else dict(NO_UPDATE_DIRECTIVE)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return build_multipart_response(
        [("directive", "application/json; charset=utf-8", body)]
    )


def no_update_directive_response() -> HttpResponse:
    """Protocol-1 "you are already up to date / no update" response."""
    return directive_response(NO_UPDATE_DIRECTIVE)


def manifest_multipart_response(manifest: dict, extensions: dict) -> HttpResponse:
    """Protocol-1 response with ``manifest`` + ``extensions`` parts."""
    manifest_body = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    extensions_body = json.dumps(
        extensions, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return build_multipart_response(
        [
            ("manifest", "application/json; charset=utf-8", manifest_body),
            ("extensions", "application/json", extensions_body),
        ]
    )


def manifest_json_response(manifest: dict) -> JsonResponse:
    """Protocol-0 response: plain JSON manifest, never cached."""
    response = JsonResponse(
        manifest, status=200, json_dumps_params={"ensure_ascii": False}
    )
    response["Cache-Control"] = NO_CACHE
    return response


def json_error(message: str, status: int = 400) -> JsonResponse:
    """Consistent JSON error body for both public and admin endpoints."""
    return JsonResponse({"error": message}, status=status)


def request_public_origin(request: HttpRequest) -> str:
    """Derive the public origin (``scheme://host``) of an incoming request."""
    return request.build_absolute_uri("/").rstrip("/")
