"""Shared helpers for the OTA test suite.

* :class:`OTATestCase` — a ``TestCase`` with an isolated ``OTA_UPDATES_DIR``.
* :func:`make_export_dir` — fabricates an ``expo export -p android`` output.
* :func:`make_zip` — turns an export directory into an upload zip.
* :func:`parse_multipart_response` — parses the Expo multipart wire format.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import uuid
import zipfile
from email import message_from_bytes, policy
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from django.http import HttpResponse
from django.test import Client, TestCase, override_settings

from ota.models import Release
from ota.publishing import PublishResult, publish_from_directory

TEST_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"
TEST_BASE_URL = "https://api.fitboook.ir"
TEST_RUNTIME_VERSION = "1.2.2"
TEST_RUNTIME_VERSION_ADMIN = "1.2.2-admin"

DEFAULT_BUNDLE_BYTES = b"var __expoBundle = 'hello ota';\n"
DEFAULT_ASSET_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes"


class OTATestCase(TestCase):
    """Base test case wiring the app to a throw-away OTA storage directory."""

    tmp_dir: Path
    updates_dir: Path
    client: Client

    def setUp(self) -> None:
        super().setUp()
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="ota-test-"))
        self.addCleanup(shutil.rmtree, self.tmp_dir, True)
        self.updates_dir = self.tmp_dir / "updates"
        self.updates_dir.mkdir(parents=True, exist_ok=True)
        self._settings_override = override_settings(
            OTA_UPDATES_DIR=self.updates_dir,
            OTA_PUBLIC_BASE_URL=TEST_BASE_URL,
            OTA_ADMIN_TOKEN=TEST_ADMIN_TOKEN,
            OTA_MAX_UPLOAD_BYTES=16 * 1024 * 1024,
            OTA_MAX_RELEASES=20,
            OTA_ASSETS_PATH="/api/updates/assets",
        )
        self._settings_override.enable()
        self.addCleanup(self._settings_override.disable)
        self.client = Client()

    # ── Convenience wrappers ─────────────────────────────────────────────

    def make_export(self, **kwargs: Any) -> Path:
        return make_export_dir(self.tmp_dir, **kwargs)

    def publish(
        self,
        export_dir: Path | None = None,
        *,
        platform: str = "android",
        runtime_version: str = TEST_RUNTIME_VERSION,
        notes: str = "",
        activate: bool = True,
        **export_kwargs: Any,
    ) -> PublishResult:
        if export_dir is None:
            export_dir = self.make_export(platform=platform, **export_kwargs)
        return publish_from_directory(
            export_dir,
            platform=platform,
            runtime_version=runtime_version,
            notes=notes,
            activate=activate,
        )

    @staticmethod
    def manifest_headers(
        *,
        platform: str = "android",
        runtime_version: str = TEST_RUNTIME_VERSION,
        protocol: int | str | None = 1,
        **extra: str,
    ) -> dict[str, str]:
        headers: dict[str, str] = {
            "expo-platform": platform,
            "expo-runtime-version": runtime_version,
        }
        if protocol is not None:
            headers["expo-protocol-version"] = str(protocol)
        headers.update(extra)
        return headers

    def get_asset(self, url: str) -> HttpResponse:
        """GET an absolute asset URL returned inside a manifest."""
        parts = urlsplit(url)
        return self.client.get(parts.path, data=parse_qs(parts.query))


# ── Fake `expo export` directories ───────────────────────────────────────────


def make_export_dir(
    directory: Path | str,
    *,
    platform: str = "android",
    bundle_rel: str | None = None,
    bundle_bytes: bytes = DEFAULT_BUNDLE_BYTES,
    assets: list[tuple[str, str, bytes]] | None = None,
    expo_config: dict[str, Any] | None = None,
    metadata_document: dict[str, Any] | None = None,
    name: str | None = None,
    extra_files: dict[str, bytes] | None = None,
) -> Path:
    """Create a folder shaped like the output of ``npx expo export -p <platform>``.

    ``assets`` is a list of ``(relative_path, ext, bytes)`` tuples; by default a
    single fake PNG asset is created. The generated file names contain a random
    token so each call produces a distinct ``metadata.json`` (and therefore a
    distinct Expo update id).
    """
    token = uuid.uuid4().hex[:10]
    export_dir = Path(directory) / (name or f"export-{token}")
    if export_dir.exists():
        raise AssertionError(f"Export directory already exists: {export_dir}")
    export_dir.mkdir(parents=True)

    bundle_rel = bundle_rel or f"_expo/static/js/{platform}/entry-{token}.hbc"
    if assets is None:
        assets = [(f"assets/asset-{token}.png", "png", DEFAULT_ASSET_BYTES)]

    bundle_path = export_dir / bundle_rel
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_bytes(bundle_bytes)

    for relative_path, _ext, data in assets:
        asset_path = export_dir / relative_path
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(data)

    if metadata_document is None:
        metadata_document = {
            "version": 0,
            "bundler": "metro",
            "fileMetadata": {
                platform: {
                    "bundle": bundle_rel,
                    "assets": [
                        {"path": relative_path, "ext": ext}
                        for relative_path, ext, _data in assets
                    ],
                }
            },
        }
    (export_dir / "metadata.json").write_text(
        json.dumps(metadata_document, ensure_ascii=False), encoding="utf-8"
    )

    if expo_config is not None:
        (export_dir / "expoConfig.json").write_text(
            json.dumps(expo_config), encoding="utf-8"
        )

    for relative_path, data in (extra_files or {}).items():
        target = export_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    return export_dir


def add_file(directory: Path | str, relative_path: str, data: bytes) -> Path:
    """Write an extra file inside an export/release directory."""
    target = Path(directory) / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def make_zip(
    export_dir: Path | str,
    *,
    top_level_folder: str | None = None,
    extra_entries: dict[str, bytes] | None = None,
) -> bytes:
    """Zip an export directory's *contents* the way CI would upload it."""
    buffer = io.BytesIO()
    export_path = Path(export_dir)
    prefix = f"{top_level_folder.strip('/')}/" if top_level_folder else ""
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(export_path.rglob("*")):
            if path.is_file():
                archive.write(
                    path, arcname=prefix + path.relative_to(export_path).as_posix()
                )
        for entry_name, data in (extra_entries or {}).items():
            archive.writestr(entry_name, data)
    return buffer.getvalue()


def make_symlink_zip() -> bytes:
    """A zip containing a unix symlink entry (must be rejected by the publisher)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("metadata.json")
        info.create_system = 3  # unix
        info.external_attr = 0o120777 << 16  # S_IFLNK | 0777
        archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


# ── Multipart / HTTP helpers ─────────────────────────────────────────────────


def response_bytes(response: HttpResponse) -> bytes:
    """Body bytes for both regular and streaming (FileResponse) responses."""
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)
    return response.content


def parse_multipart_response(response: HttpResponse) -> dict[str, Message]:
    """Parse an Expo ``multipart/mixed`` response into ``{part name: Message}``."""
    content_type = response.headers.get("Content-Type", "")
    if not content_type.startswith("multipart/mixed"):
        raise AssertionError(f"Expected multipart/mixed response, got {content_type!r}")
    raw = (
        b"Content-Type: "
        + content_type.encode("latin-1")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + response_bytes(response)
    )
    message = message_from_bytes(raw, policy=policy.default)
    parts: dict[str, Message] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="Content-Disposition")
        if name:
            parts[name] = part
    return parts


def parse_multipart_json(response: HttpResponse, part_name: str) -> Any:
    """Decode one JSON part of a multipart response."""
    parts = parse_multipart_response(response)
    if part_name not in parts:
        raise AssertionError(
            f"Missing multipart part {part_name!r}; parts were {sorted(parts)}"
        )
    payload = parts[part_name].get_payload(decode=True)
    return json.loads(payload.decode("utf-8"))


def latest_release(
    runtime_version: str = TEST_RUNTIME_VERSION, platform: str = "android"
) -> Release | None:
    """Small convenience wrapper for assertions."""
    from ota.services import get_latest_release

    return get_latest_release(runtime_version, platform)
