"""Typed exceptions for the OTA app.

Every exception carries the HTTP status code that the public/admin API should
return for it. Views translate ``OTAError`` into a JSON error response, so new
error cases only need to raise the right class instead of duplicating status
handling in every view.
"""

from __future__ import annotations


class OTAError(Exception):
    """Base class for all expected OTA errors (never a server bug)."""

    status: int = 400

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status


class InvalidRequest(OTAError):
    """The request is malformed (missing/invalid headers or query params)."""

    status = 400


class InvalidRuntimeVersion(InvalidRequest):
    """The runtimeVersion is missing or cannot safely be used as a path segment."""

    status = 400


class UnsupportedPlatform(InvalidRequest):
    """The provided platform is not ``android`` or ``ios``."""

    status = 400


class InvalidBundleError(OTAError):
    """The uploaded/pointed-to export folder is not a valid ``expo export`` output."""

    status = 400


class InvalidArchive(InvalidBundleError):
    """The uploaded zip cannot be opened or contains unsafe entries."""

    status = 400


class UnsafePathError(InvalidBundleError):
    """A path tries to escape its allowed root (path traversal)."""

    status = 400


class PublishTooLarge(OTAError):
    """The uploaded archive is bigger than ``OTA_MAX_UPLOAD_BYTES``."""

    status = 413


class UnsupportedProtocolVersion(InvalidRequest):
    """The client requested an unknown ``expo-protocol-version``."""

    status = 406
