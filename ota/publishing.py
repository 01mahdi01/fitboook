"""Publishing OTA releases from an ``expo export`` directory or a zip upload.

Two entry points share the same validation and storage pipeline:

* :func:`publish_from_directory` — used by ``manage.py ota_publish`` (the
  normal, on-server release workflow),
* :func:`publish_from_zip` — used by ``POST /api/admin/updates/publish/`` so
  CI can upload ``zip -r dist-ota.zip dist-ota`` (zip-slip and zip-bomb safe).

Storage layout (same as the proven nodoost reference implementation)::

    <OTA_UPDATES_DIR>/<runtimeVersion>/<timestampMillis>/
        metadata.json
        expoConfig.json
        _expo/static/js/android/entry-<hash>.hbc
        assets/<hash>.<ext>

A release is invisible to clients until its DB row is committed, so a failed
publish can never serve a half-copied bundle: rows are only created after the
files have been copied to their final directory.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import stat
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from django.db import transaction
from django.utils import timezone

from . import conf
from .exceptions import (
    InvalidArchive,
    InvalidBundleError,
    OTAError,
    PublishTooLarge,
    UnsafePathError,
    UnsupportedPlatform,
)
from .metadata import (
    ExportMetadata,
    PlatformMetadata,
    content_type_for_extension,
    file_digests,
    read_export_metadata,
)
from .models import PLATFORMS, Release
from .paths import (
    ensure_within,
    looks_like_timestamp_dir,
    safe_join,
    safe_relative_path,
    validate_runtime_version,
)

logger = logging.getLogger(__name__)

#: Defensive limits for uploaded zips.
MAX_ZIP_ENTRIES = 20_000
COPY_CHUNK_SIZE = 1024 * 1024
#: Temporary staging/upload folders older than this are leftovers from a crash.
STALE_TEMP_MAX_AGE_SECONDS = 60 * 60


@dataclass(frozen=True)
class PublishResult:
    """Outcome of a publish operation."""

    release: Release
    created: bool
    pruned_release_ids: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "release": self.release.as_dict(),
            "created": self.created,
            "prunedReleaseIds": list(self.pruned_release_ids),
        }


# ── Public API ───────────────────────────────────────────────────────────────


def publish_from_directory(
    export_dir: Path | str,
    *,
    platform: str,
    runtime_version: str,
    notes: str = "",
    activate: bool = True,
    created_by: Any = None,
    max_releases: int | None = None,
) -> PublishResult:
    """Validate ``export_dir`` (an ``expo export`` output) and publish it.

    Raises :class:`OTAError` subclasses for invalid input. On any failure the
    partially copied files are removed and no DB row is created.
    """
    platform = validate_platform(platform)
    runtime_version = validate_runtime_version(runtime_version)
    export_path = Path(export_dir)
    # The platform metadata is validated inside _validate_export; only the
    # resulting file hash map is needed here.
    metadata, _platform_metadata, asset_metadata = _validate_export(
        export_path, platform
    )

    published_at = timezone.now()
    updates_root = conf.updates_dir()
    try:
        updates_root.mkdir(parents=True, exist_ok=True)
        runtime_dir = updates_root / runtime_version
        runtime_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_stale_temp_dirs(runtime_dir, prefix=".staging-")
    except OSError as exc:
        raise InvalidBundleError(
            f"Cannot prepare OTA storage directory: {exc}"
        ) from exc

    staging_dir = _make_staging_dir(runtime_dir)
    final_dir: Path | None = None
    try:
        _copy_export_tree(export_path, staging_dir, runtime_dir=runtime_dir)

        # Guard against the source changing while it is being copied.
        copied_metadata = read_export_metadata(staging_dir)
        if copied_metadata.sha256_hex != metadata.sha256_hex:
            raise InvalidBundleError(
                "metadata.json changed while publishing (did an export run concurrently?); retry"
            )

        final_dir = _claim_timestamp_directory(runtime_dir, staging_dir, published_at)
        storage_path = f"{runtime_version}/{final_dir.name}"

        release, created, previous_storage = _save_release(
            metadata=metadata,
            platform=platform,
            runtime_version=runtime_version,
            notes=notes,
            activate=activate,
            created_by=created_by,
            storage_path=storage_path,
            asset_metadata=asset_metadata,
            published_at=published_at,
        )
    except BaseException:
        _remove_tree_quietly(staging_dir)
        if final_dir is not None:
            _remove_tree_quietly(final_dir)
        raise

    # Replaced files of an old row: delete them once no row references them.
    if (
        previous_storage
        and previous_storage != storage_path
        and not Release.objects.filter(storage_path=previous_storage).exists()
    ):
        _delete_storage_path(previous_storage)

    try:
        pruned = tuple(prune_releases(runtime_version, max_releases))
    except Exception:  # pragma: no cover - retention must never break publishing
        logger.exception(
            "OTA retention pruning failed for runtimeVersion=%s", runtime_version
        )
        pruned = ()

    logger.info(
        "Published OTA release %s (runtimeVersion=%s platform=%s updateId=%s path=%s)",
        release.pk,
        runtime_version,
        platform,
        metadata.update_id,
        storage_path,
    )
    return PublishResult(release=release, created=created, pruned_release_ids=pruned)


def publish_from_zip(
    upload: BinaryIO | bytes | bytearray,
    *,
    platform: str,
    runtime_version: str,
    notes: str = "",
    activate: bool = True,
    created_by: Any = None,
    max_releases: int | None = None,
) -> PublishResult:
    """Publish a zip containing the *contents* of an ``expo export`` folder.

    Safe against path traversal (zip-slip), symlink entries and decompression
    bombs; archives bigger than ``OTA_MAX_UPLOAD_BYTES`` are rejected.
    """
    platform = validate_platform(platform)
    runtime_version = validate_runtime_version(runtime_version)
    max_bytes = conf.max_upload_bytes()

    if isinstance(upload, (bytes, bytearray)):
        if len(upload) > max_bytes:
            raise PublishTooLarge(
                f"Uploaded bundle is too large ({len(upload)} bytes, max {max_bytes} bytes)"
            )
        source: BinaryIO = io.BytesIO(upload)
        archive_size: int | None = len(upload)
    else:
        source = upload
        archive_size = _stream_size(source)
        if archive_size is not None and archive_size > max_bytes:
            raise PublishTooLarge(
                f"Uploaded bundle is too large ({archive_size} bytes, max {max_bytes} bytes)"
            )

    updates_root = conf.updates_dir()
    try:
        updates_root.mkdir(parents=True, exist_ok=True)
        incoming_root = updates_root / ".incoming"
        incoming_root.mkdir(parents=True, exist_ok=True)
        _cleanup_stale_temp_dirs(incoming_root, prefix=".zip-")
        extraction_dir = Path(tempfile.mkdtemp(prefix=".zip-", dir=incoming_root))
    except OSError as exc:
        raise InvalidBundleError(f"Cannot prepare OTA upload directory: {exc}") from exc

    try:
        _extract_zip(source, extraction_dir, max_bytes=max_bytes)
        export_root = _locate_export_root(extraction_dir)
        return publish_from_directory(
            export_root,
            platform=platform,
            runtime_version=runtime_version,
            notes=notes,
            activate=activate,
            created_by=created_by,
            max_releases=max_releases,
        )
    finally:
        _remove_tree_quietly(extraction_dir)


def validate_platform(platform: str | None) -> str:
    """Normalize ``platform`` or raise :class:`UnsupportedPlatform`."""
    normalized = (platform or "").strip().lower()
    if normalized not in PLATFORMS:
        allowed = ", ".join(PLATFORMS)
        raise UnsupportedPlatform(
            f"Unsupported platform {platform!r}; expected one of: {allowed}"
        )
    return normalized


# ── Export validation ────────────────────────────────────────────────────────


def _validate_export(
    export_dir: Path,
    platform: str,
) -> tuple[ExportMetadata, PlatformMetadata, dict[str, dict[str, str]]]:
    """Validate an ``expo export`` folder and hash all files this platform needs."""
    metadata = read_export_metadata(export_dir)
    platform_metadata = metadata.require_platform(platform)

    asset_metadata: dict[str, dict[str, str]] = {}
    for relative_path in platform_metadata.all_paths:
        if relative_path in asset_metadata:
            continue
        full_path = safe_join(export_dir, relative_path, field="metadata file path")
        if not full_path.is_file():
            raise InvalidBundleError(
                f"File referenced in metadata.json is missing from the export: {relative_path!r}"
            )
        try:
            digest, key = file_digests(full_path)
        except OSError as exc:
            raise InvalidBundleError(
                f"Cannot read export file {relative_path!r}: {exc}"
            ) from exc
        if relative_path == platform_metadata.bundle:
            content_type = "application/javascript"
        else:
            ext = next(
                (
                    asset.ext
                    for asset in platform_metadata.assets
                    if asset.path == relative_path
                ),
                "",
            )
            content_type = content_type_for_extension(ext)
        asset_metadata[relative_path] = {
            "hash": digest,
            "key": key,
            "content_type": content_type,
        }

    if platform_metadata.bundle not in asset_metadata:
        raise InvalidBundleError(
            f"metadata.json bundle for platform {platform!r} was not found in the export"
        )
    return metadata, platform_metadata, asset_metadata


# ── Filesystem helpers ───────────────────────────────────────────────────────


def _make_staging_dir(runtime_dir: Path) -> Path:
    """Return a unique hidden staging path next to the final timestamp folders.

    The directory itself is created by :func:`_copy_export_tree`; keeping it
    non-existent until then makes ``os.replace`` into the final name atomic.
    """
    return runtime_dir / f".staging-{uuid.uuid4().hex}"


def _claim_timestamp_directory(
    runtime_dir: Path,
    staging_dir: Path,
    published_at: Any,
) -> Path:
    """Atomically move the staging dir to ``<runtimeVersion>/<timestampMillis>``."""
    timestamp_ms = int(published_at.timestamp() * 1000)
    for _attempt in range(100):
        candidate = runtime_dir / str(timestamp_ms)
        try:
            os.replace(staging_dir, candidate)
            return candidate
        except OSError as exc:
            if candidate.exists():
                timestamp_ms += 1
                continue
            raise InvalidBundleError(
                f"Cannot move published files into place: {exc}"
            ) from exc
    raise InvalidBundleError(
        "Cannot allocate a unique publish timestamp; retry"
    )  # pragma: no cover


def _copy_export_tree(source: Path, destination: Path, *, runtime_dir: Path) -> None:
    """Copy an export folder, refusing symlinks and special files.

    Requirement: files are always *copied* (never symlinked), so the published
    tree stays valid even when the CI export directory is deleted afterwards.
    """
    source = Path(source).resolve()
    resolved_destination = Path(destination).resolve()
    if resolved_destination == source or source in resolved_destination.parents:
        raise InvalidBundleError(
            "The export directory must not contain the OTA storage directory"
        )
    if destination.exists():  # pragma: no cover - staging dir is always fresh
        raise InvalidBundleError(f"Staging directory already exists: {destination}")

    try:
        destination.mkdir(parents=True, exist_ok=False)
        for current_dir, dir_names, file_names in os.walk(source, followlinks=False):
            current_path = Path(current_dir)
            relative_dir = current_path.relative_to(source)
            target_dir = destination / relative_dir

            for dir_name in dir_names:
                source_dir = current_path / dir_name
                if source_dir.is_symlink():
                    raise InvalidBundleError(
                        f"Symlinks are not allowed in an export directory: {source_dir}"
                    )
                try:
                    safe_relative_path(
                        (relative_dir / dir_name).as_posix(), field="directory"
                    )
                except UnsafePathError as exc:
                    raise InvalidBundleError(str(exc)) from exc
                (target_dir / dir_name).mkdir(exist_ok=True)

            for file_name in file_names:
                source_file = current_path / file_name
                if source_file.is_symlink():
                    raise InvalidBundleError(
                        f"Symlinks are not allowed in an export directory: {source_file}"
                    )
                if not source_file.is_file():
                    raise InvalidBundleError(
                        f"Unsupported file type in export: {source_file}"
                    )
                relative_file = source_file.relative_to(source)
                safe_relative_path(relative_file.as_posix(), field="file path")
                target_file = destination / relative_file
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_file, target_file)
                try:
                    os.chmod(target_file, 0o644)
                except OSError:  # pragma: no cover - non-POSIX filesystems
                    pass

        try:
            os.chmod(destination, 0o755)
        except OSError:  # pragma: no cover
            pass
    except OSError as exc:
        raise InvalidBundleError(f"Cannot copy export directory: {exc}") from exc


def _cleanup_stale_temp_dirs(
    parent: Path,
    *,
    prefix: str,
    max_age_seconds: int = STALE_TEMP_MAX_AGE_SECONDS,
) -> None:
    """Remove temporary folders left behind by a crashed/killed publish."""
    try:
        entries = list(parent.iterdir())
    except OSError:  # pragma: no cover - parent disappears between calls
        return
    cutoff = time.time() - max_age_seconds
    for entry in entries:
        if not entry.name.startswith(prefix):
            continue
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                logger.warning("Removed stale OTA temporary directory %s", entry)
        except OSError:  # pragma: no cover - best effort cleanup
            continue


def _remove_tree_quietly(path: Path | None) -> None:
    if path is None:
        return
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:  # pragma: no cover - ignore_errors already covers this
        logger.warning("Could not remove temporary OTA path %s", path)


def _delete_storage_path(storage_path: str) -> None:
    """Remove one ``<runtimeVersion>/<timestamp>`` folder, refusing anything else."""
    root = conf.updates_dir()
    parts = [part for part in str(storage_path).split("/") if part]
    if len(parts) != 2:
        logger.error("Refusing to delete unexpected OTA storage path: %r", storage_path)
        return
    try:
        runtime_version = validate_runtime_version(parts[0])
        if not looks_like_timestamp_dir(parts[1]):
            logger.error(
                "Refusing to delete non-timestamp OTA folder: %r", storage_path
            )
            return
        target = ensure_within(
            root / runtime_version, root / runtime_version / parts[1]
        )
    except OTAError as exc:
        logger.error(
            "Refusing to delete unsafe OTA storage path %r: %s", storage_path, exc
        )
        return
    _remove_tree_quietly(target)
    logger.info("Deleted OTA release files at %s", storage_path)


# ── DB persistence / retention ───────────────────────────────────────────────


def _save_release(
    *,
    metadata: ExportMetadata,
    platform: str,
    runtime_version: str,
    notes: str,
    activate: bool,
    created_by: Any,
    storage_path: str,
    asset_metadata: dict[str, dict[str, str]],
    published_at: Any,
) -> tuple[Release, bool, str | None]:
    """Insert or update the DB row; returns ``(release, created, previous_storage)``."""
    with transaction.atomic():
        existing = (
            Release.objects.select_for_update()
            .filter(
                runtime_version=runtime_version,
                platform=platform,
                update_id=metadata.update_id,
            )
            .first()
        )
        if existing is not None:
            previous_storage = existing.storage_path
            existing.metadata = metadata.document
            existing.asset_metadata = asset_metadata
            existing.storage_path = storage_path
            existing.published_at = published_at
            existing.notes = notes
            existing.is_active = activate
            if created_by is not None:
                existing.created_by = created_by
            existing.save(
                update_fields=[
                    "metadata",
                    "asset_metadata",
                    "storage_path",
                    "published_at",
                    "notes",
                    "is_active",
                    "created_by",
                ]
            )
            return existing, False, previous_storage

        release = Release.objects.create(
            runtime_version=runtime_version,
            platform=platform,
            update_id=metadata.update_id,
            metadata=metadata.document,
            asset_metadata=asset_metadata,
            storage_path=storage_path,
            notes=notes,
            is_active=activate,
            published_at=published_at,
            created_by=created_by,
        )
        return release, True, None


def prune_releases(runtime_version: str, max_releases: int | None = None) -> list[int]:
    """Keep only the newest ``max_releases`` rows for ``runtime_version``.

    Rows outside the retention window are deleted together with their files
    (unless another row still references the same storage directory). Rollback
    therefore works within the retention window; the currently served release
    is always the newest row, so it is never pruned.
    """
    limit = conf.max_releases() if max_releases is None else int(max_releases)
    if limit <= 0:
        return []
    releases = list(
        Release.objects.filter(runtime_version=runtime_version).newest_first()
    )
    stale = releases[limit:]
    if not stale:
        return []

    deleted_ids: list[int] = []
    for release in stale:
        release_id = release.pk
        storage_path = release.storage_path
        try:
            release.delete()
        except Exception:  # pragma: no cover - keep publishing even if pruning hiccups
            logger.exception("Could not prune OTA release %s", release_id)
            continue
        deleted_ids.append(int(release_id))
        if not Release.objects.filter(storage_path=storage_path).exists():
            _delete_storage_path(storage_path)
    if deleted_ids:
        logger.info(
            "Pruned %d old OTA release(s) for runtimeVersion=%s: %s",
            len(deleted_ids),
            runtime_version,
            deleted_ids,
        )
    return deleted_ids


# ── Zip handling ─────────────────────────────────────────────────────────────


def _stream_size(stream: BinaryIO) -> int | None:
    """Best-effort size of a seekable uploaded stream."""
    try:
        position = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(position)
        return int(size)
    except (
        AttributeError,
        OSError,
        ValueError,
    ):  # pragma: no cover - non-seekable stream
        return None


def _extract_zip(
    source: BinaryIO | Path,
    destination: Path,
    *,
    max_bytes: int,
) -> None:
    """Safely extract an uploaded zip (zip-slip, symlink and zip-bomb protection)."""
    destination.mkdir(parents=True, exist_ok=True)
    total_uncompressed = 0
    seen_names: set[str] = set()

    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if not infos:
                raise InvalidArchive("The uploaded zip archive is empty")
            if len(infos) > MAX_ZIP_ENTRIES:
                raise InvalidArchive(
                    f"The uploaded zip has too many entries ({len(infos)}, max {MAX_ZIP_ENTRIES})"
                )

            for info in infos:
                if info.is_dir():
                    continue
                if info.flag_bits & 0x1:
                    raise InvalidArchive(
                        f"Encrypted zip entries are not supported: {info.filename!r}"
                    )
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise InvalidArchive(
                        f"Symlink entries are not allowed in a bundle zip: {info.filename!r}"
                    )

                try:
                    normalized = safe_relative_path(
                        info.filename, field="zip entry name"
                    )
                except UnsafePathError as exc:
                    raise InvalidArchive(str(exc)) from exc
                if normalized in seen_names:
                    raise InvalidArchive(f"Duplicate zip entry: {normalized!r}")
                seen_names.add(normalized)

                total_uncompressed += info.file_size
                if total_uncompressed > max_bytes:
                    raise PublishTooLarge(
                        f"Uncompressed bundle is too large (max {max_bytes} bytes)"
                    )

                try:
                    target = safe_join(destination, normalized, field="zip entry name")
                except UnsafePathError as exc:
                    raise InvalidArchive(str(exc)) from exc
                target.parent.mkdir(parents=True, exist_ok=True)

                written = 0
                with archive.open(info) as source_file, open(
                    target, "wb"
                ) as target_file:
                    while True:
                        chunk = source_file.read(COPY_CHUNK_SIZE)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > max_bytes:
                            raise PublishTooLarge(
                                f"Uncompressed bundle is too large (max {max_bytes} bytes)"
                            )
                        target_file.write(chunk)
                try:
                    os.chmod(target, 0o644)
                except OSError:  # pragma: no cover
                    pass
    except zipfile.BadZipFile as exc:
        raise InvalidArchive("The uploaded file is not a valid zip archive") from exc
    except OSError as exc:
        raise InvalidArchive(f"Cannot read the uploaded zip archive: {exc}") from exc


def _locate_export_root(extracted: Path) -> Path:
    """Find ``metadata.json`` in the extraction root; descend into a single folder.

    CI often zips like ``zip -r dist-ota.zip dist-ota`` which produces a single
    top-level folder. Accepting that avoids a class of "metadata.json not
    found" support tickets while still rejecting anything ambiguous.
    """
    if (extracted / "metadata.json").is_file():
        return extracted
    candidates = [
        child
        for child in extracted.iterdir()
        if child.is_dir()
        and not child.name.startswith(".")
        and (child / "metadata.json").is_file()
    ]
    if len(candidates) == 1:
        return candidates[0]
    return extracted
