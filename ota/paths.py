"""Path-safety helpers.

All user/archive/database controlled paths are funnelled through this module
before touching the filesystem:

* ``validate_runtime_version`` — runtimeVersion ends up as a directory name.
* ``safe_relative_path`` — normalizes a relative path and rejects traversal,
  absolute paths, NUL bytes, Windows drive letters, etc.
* ``safe_join`` / ``ensure_within`` — resolve a relative path inside a base
  directory and guarantee the result cannot escape it (symlinks included).
"""

from __future__ import annotations

import re
from pathlib import Path

from .exceptions import InvalidRuntimeVersion, UnsafePathError

# runtimeVersion is a developer-chosen string, but it becomes a folder name and
# is echoed back in JSON/URLs, so we deliberately keep it to a safe charset.
# Examples in this project: "1.2.2", "1.2.2-admin", "1.2.2+42".
_RUNTIME_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+@-]{0,127}$")

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def validate_runtime_version(
    value: str | None, *, field: str = "runtimeVersion"
) -> str:
    """Return a normalized, path-safe runtimeVersion or raise ``InvalidRuntimeVersion``."""
    normalized = (value or "").strip()
    if not normalized:
        raise InvalidRuntimeVersion(f"{field} is required")
    if len(normalized) > 128:
        raise InvalidRuntimeVersion(f"{field} is too long (max 128 characters)")
    if not _RUNTIME_VERSION_RE.fullmatch(normalized):
        raise InvalidRuntimeVersion(
            f"{field} contains unsupported characters; allowed: letters, digits, "
            f'\'._+@-\', e.g. "1.2.2" or "1.2.2-admin"'
        )
    return normalized


def safe_relative_path(value: str | None, *, field: str = "path") -> str:
    """Normalize ``value`` into a portable relative path (``a/b/c``).

    Raises ``UnsafePathError`` for absolute paths, parent traversal (``..``),
    NUL bytes, Windows drive letters and empty values.
    """
    raw = value or ""
    if "\x00" in raw:
        raise UnsafePathError(f"Invalid {field}: NUL byte is not allowed")
    normalized = raw.strip().replace("\\", "/")
    if not normalized:
        raise UnsafePathError(f"Invalid {field}: value is empty")
    if normalized.startswith("/"):
        raise UnsafePathError(
            f"Invalid {field}: absolute paths are not allowed ({raw!r})"
        )
    if _WINDOWS_DRIVE_RE.match(normalized):
        raise UnsafePathError(
            f"Invalid {field}: drive letters are not allowed ({raw!r})"
        )

    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise UnsafePathError(
            f"Invalid {field}: path traversal is not allowed ({raw!r})"
        )
    return "/".join(parts)


def ensure_within(base: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` and ensure it is ``base`` or inside it."""
    resolved_base = Path(base).resolve()
    resolved = Path(candidate).resolve()
    if resolved != resolved_base and resolved_base not in resolved.parents:
        raise UnsafePathError(f"Path escapes its root: {candidate}")
    return resolved


def safe_join(base: Path, relative: str | None, *, field: str = "path") -> Path:
    """Join and validate a relative path inside ``base``."""
    normalized = safe_relative_path(relative, field=field)
    return ensure_within(base, Path(base) / normalized)


def looks_like_timestamp_dir(name: str) -> bool:
    """True when ``name`` is a numeric millisecond timestamp folder name."""
    return bool(name) and name.isascii() and name.isdigit()
