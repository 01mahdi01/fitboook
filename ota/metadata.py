"""Parsing, validation and hashing of ``expo export`` output metadata.

``npx expo export -p android`` produces a folder like::

    dist-ota/
    ├── metadata.json
    ├── expoConfig.json
    ├── _expo/static/js/android/entry-<hash>.hbc
    └── assets/<...>

``metadata.json`` has this shape (version 0, metro bundler)::

    {
      "version": 0,
      "bundler": "metro",
      "fileMetadata": {
        "android": {
          "bundle": "_expo/static/js/android/entry-<hash>.hbc",
          "assets": [{"path": "assets/<hash>.png", "ext": "png"}, ...]
        }
      }
    }

This module validates that document, derives the Expo update id
(``sha256(metadata.json bytes)`` formatted as a UUID) and computes the per-file
integrity hashes used inside the manifest.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .exceptions import InvalidBundleError, UnsafePathError
from .paths import safe_relative_path

logger = logging.getLogger(__name__)

PLATFORMS = ("android", "ios")

#: Metadata files are tiny; anything bigger is not a real ``expo export`` output.
MAX_METADATA_BYTES = 16 * 1024 * 1024
#: expoConfig.json is the app config snapshot injected into the manifest.
MAX_EXPO_CONFIG_BYTES = 16 * 1024 * 1024

_EXT_RE = re.compile(r"^[a-z0-9]{1,16}$")

#: Files that must never be exposed as downloadable assets.
_INTERNAL_FILENAMES = frozenset({"metadata.json", "expoConfig.json"})

#: Explicit MIME map for the asset types Expo apps ship (fonts, images, media).
_CONTENT_TYPES: Mapping[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "avif": "image/avif",
    "svg": "image/svg+xml",
    "ico": "image/x-icon",
    "ttf": "font/ttf",
    "otf": "font/otf",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "webm": "video/webm",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "json": "application/json",
    "js": "application/javascript",
    "hbc": "application/javascript",
    "bundle": "application/javascript",
    "css": "text/css",
    "html": "text/html",
    "txt": "text/plain",
    "pdf": "application/pdf",
    "zip": "application/zip",
}


# ── Hashing helpers ──────────────────────────────────────────────────────────


def content_type_for_extension(extension: str | None) -> str:
    """Return a MIME type for ``extension`` (with or without a leading dot)."""
    ext = (extension or "").strip().lower().lstrip(".")
    if not ext:
        return "application/octet-stream"
    if ext in _CONTENT_TYPES:
        return _CONTENT_TYPES[ext]
    guessed, _encoding = mimetypes.guess_type(f"file.{ext}")
    return guessed or "application/octet-stream"


def base64url_sha256(digest: bytes) -> str:
    """Base64URL-encode a raw SHA-256 digest without ``=`` padding (spec: ``hash``)."""
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def sha256_hex(data: bytes) -> str:
    """Lower-case hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def format_update_id(hex_digest: str) -> str:
    """Turn the first 32 hex chars of a SHA-256 digest into a UUID-shaped id.

    Expo requires ``manifest.id`` to be a UUID. The reference server derives it
    from ``sha256(metadata.json)``; we keep exactly the same derivation so the
    update id is stable for a given export::

        sha256 hex: ba7816bf8f01cfea414140de5dae2223b00361a3...
        update id:  ba7816bf-8f01-cfea-4141-40de5dae2223
    """
    if len(hex_digest) < 32:
        raise ValueError("A SHA-256 hex digest must have at least 32 characters")
    h = hex_digest[:32].lower()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def update_id_from_metadata_bytes(raw_metadata: bytes) -> str:
    """Expo update id for a raw ``metadata.json`` payload (deterministic)."""
    return format_update_id(sha256_hex(raw_metadata))


def file_digests(path: Path) -> tuple[str, str]:
    """Compute ``(base64url_sha256, md5_hex)`` for a file without loading it fully.

    ``hash`` is the base64url SHA-256 required by the Expo protocol and ``key``
    is the md5 hex string Expo uses to reference the asset from JS code.
    """
    sha = hashlib.sha256()
    md5 = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
            md5.update(chunk)
    return base64url_sha256(sha.digest()), md5.hexdigest()


# ── Metadata model ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AssetRef:
    """One asset entry from ``fileMetadata[platform].assets``."""

    path: str
    ext: str

    @property
    def file_extension(self) -> str:
        return f".{self.ext}" if self.ext else ""


@dataclass(frozen=True)
class PlatformMetadata:
    """Bundle + assets of a single platform inside an export."""

    platform: str
    bundle: str
    assets: tuple[AssetRef, ...]

    @property
    def all_paths(self) -> tuple[str, ...]:
        return (self.bundle, *(asset.path for asset in self.assets))


@dataclass(frozen=True)
class ExportMetadata:
    """Validated representation of ``metadata.json``."""

    raw: bytes
    document: dict[str, Any]
    version: int
    bundler: str
    file_metadata: Mapping[str, PlatformMetadata]
    sha256_hex: str

    @property
    def update_id(self) -> str:
        return format_update_id(self.sha256_hex)

    def require_platform(self, platform: str) -> PlatformMetadata:
        """Return platform metadata or raise a descriptive ``InvalidBundleError``."""
        try:
            return self.file_metadata[platform]
        except KeyError:
            available = ", ".join(sorted(self.file_metadata)) or "none"
            raise InvalidBundleError(
                f"metadata.json has no bundle for platform {platform!r} "
                f"(available platforms: {available}). Re-export with "
                f"`npx expo export -p {platform} ...`"
            ) from None


# ── Parsing / validation ─────────────────────────────────────────────────────


def _require_mapping(value: Any, *, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidBundleError(f"metadata.json: {where} must be a JSON object")
    return value


def _normalize_ext(value: Any, *, path: str, where: str) -> str:
    raw = value.strip().lower().lstrip(".") if isinstance(value, str) else ""
    if raw and not _EXT_RE.fullmatch(raw):
        raise InvalidBundleError(
            f"metadata.json: {where}.ext has invalid value {value!r}"
        )
    if raw:
        return raw
    suffix = Path(path).suffix.lower().lstrip(".")
    return suffix if _EXT_RE.fullmatch(suffix) else ""


def _split_metadata_path(raw: Any, *, where: str) -> str:
    if not isinstance(raw, str):
        raise InvalidBundleError(f"metadata.json: {where} must be a string")
    try:
        return safe_relative_path(raw, field=f"metadata.json {where}")
    except UnsafePathError as exc:
        raise InvalidBundleError(str(exc)) from exc


def _parse_platform(platform: str, value: Any, *, where: str) -> PlatformMetadata:
    data = _require_mapping(value, where=f"{where} ({platform})")
    if "bundle" not in data:
        raise InvalidBundleError(
            f"metadata.json: {where}.bundle is missing (platform {platform})"
        )
    bundle = _split_metadata_path(data["bundle"], where=f"{where}.bundle")
    base_name = bundle.rsplit("/", 1)[-1]
    if base_name in _INTERNAL_FILENAMES:
        raise InvalidBundleError(
            f"metadata.json: {where}.bundle must not point to an internal file ({bundle!r})"
        )

    raw_assets = data.get("assets", [])
    if raw_assets is None:
        raw_assets = []
    if not isinstance(raw_assets, list):
        raise InvalidBundleError(f"metadata.json: {where}.assets must be a JSON array")

    assets: list[AssetRef] = []
    seen = {bundle}
    for index, item in enumerate(raw_assets):
        item_where = f"{where}.assets[{index}]"
        asset_data = _require_mapping(item, where=item_where)
        if "path" not in asset_data:
            raise InvalidBundleError(f"metadata.json: {item_where}.path is missing")
        path = _split_metadata_path(asset_data["path"], where=f"{item_where}.path")
        if path.rsplit("/", 1)[-1] in _INTERNAL_FILENAMES:
            raise InvalidBundleError(
                f"metadata.json: {item_where}.path must not point to an internal file ({path!r})"
            )
        if path in seen:
            raise InvalidBundleError(
                f"metadata.json: duplicate asset path {path!r} in platform {platform!r}"
            )
        seen.add(path)
        ext = _normalize_ext(asset_data.get("ext"), path=path, where=item_where)
        assets.append(AssetRef(path=path, ext=ext))

    return PlatformMetadata(platform=platform, bundle=bundle, assets=tuple(assets))


def parse_export_metadata(raw: bytes) -> ExportMetadata:
    """Validate raw ``metadata.json`` bytes and return a typed representation."""
    if not isinstance(raw, (bytes, bytearray)):
        raise InvalidBundleError("metadata.json could not be read as bytes")
    raw_bytes = bytes(raw)
    if len(raw_bytes) > MAX_METADATA_BYTES:
        raise InvalidBundleError(
            f"metadata.json is too large ({len(raw_bytes)} bytes, "
            f"max {MAX_METADATA_BYTES} bytes)"
        )
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidBundleError(f"metadata.json is not valid JSON: {exc}") from exc

    document = _require_mapping(data, where="root")

    version = document.get("version", 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise InvalidBundleError(
            "metadata.json: version must be a non-negative integer"
        )

    bundler = document.get("bundler")
    if bundler is not None and not isinstance(bundler, str):
        raise InvalidBundleError("metadata.json: bundler must be a string")

    raw_file_metadata = document.get("fileMetadata")
    if raw_file_metadata is None:
        raise InvalidBundleError(
            "metadata.json: fileMetadata is missing. Is this really an `expo export` output?"
        )
    file_metadata_document = _require_mapping(raw_file_metadata, where="fileMetadata")
    if not file_metadata_document:
        raise InvalidBundleError("metadata.json: fileMetadata is empty")

    parsed: dict[str, PlatformMetadata] = {}
    for raw_platform, value in file_metadata_document.items():
        if not isinstance(raw_platform, str) or not raw_platform.strip():
            raise InvalidBundleError(
                "metadata.json: fileMetadata keys must be platform names"
            )
        platform = raw_platform.strip().lower()
        if platform in parsed:
            raise InvalidBundleError(
                f"metadata.json: duplicate platform key {raw_platform!r}"
            )
        parsed[platform] = _parse_platform(
            platform, value, where=f"fileMetadata[{platform}]"
        )

    for platform in PLATFORMS:
        metadata = parsed.get(platform)
        if metadata is not None and not metadata.bundle:
            raise InvalidBundleError(
                f"metadata.json: empty bundle path for platform {platform}"
            )

    return ExportMetadata(
        raw=raw_bytes,
        document=document,
        version=version,
        bundler=bundler or "",
        file_metadata=parsed,
        sha256_hex=sha256_hex(raw_bytes),
    )


def read_export_metadata(export_dir: Path | str) -> ExportMetadata:
    """Read and validate ``<export_dir>/metadata.json``."""
    directory = Path(export_dir)
    if not directory.is_dir():
        raise InvalidBundleError(f"Export directory does not exist: {directory}")
    metadata_path = directory / "metadata.json"
    if not metadata_path.is_file():
        raise InvalidBundleError(
            f"metadata.json not found in {directory}. Publish the output of "
            "`npx expo export -p android --output-dir dist-ota`."
        )
    try:
        size = metadata_path.stat().st_size
    except OSError as exc:
        raise InvalidBundleError(f"Cannot read metadata.json: {exc}") from exc
    if size > MAX_METADATA_BYTES:
        raise InvalidBundleError(
            f"metadata.json is too large ({size} bytes, max {MAX_METADATA_BYTES} bytes)"
        )
    try:
        raw = metadata_path.read_bytes()
    except OSError as exc:
        raise InvalidBundleError(f"Cannot read metadata.json: {exc}") from exc
    return parse_export_metadata(raw)


def load_expo_config(export_dir: Path | str) -> dict[str, Any]:
    """Read ``expoConfig.json`` (the ``extra.expoClient`` payload) if present.

    A missing or malformed file is not fatal: the manifest simply carries an
    empty object, exactly like the reference implementation.
    """
    path = Path(export_dir) / "expoConfig.json"
    try:
        if not path.is_file():
            return {}
        if path.stat().st_size > MAX_EXPO_CONFIG_BYTES:
            logger.warning("expoConfig.json is unexpectedly large; ignoring (%s)", path)
            return {}
        raw = path.read_bytes()
    except OSError as exc:
        logger.warning("Cannot read expoConfig.json (%s): %s", path, exc)
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("Invalid expoConfig.json (%s): %s", path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("expoConfig.json is not a JSON object; ignoring (%s)", path)
        return {}
    return data
