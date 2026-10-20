"""Domain models and exceptions for Calibre operations."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BookExport:
    """Represents an EPUB file exported from a Calibre library."""

    file_path: Path
    format: str
    size_bytes: int


@dataclass(frozen=True)
class AddedBook:
    """Represents a book record newly added to a Calibre library."""

    calibre_id: str
    title: str
    formats: tuple[str, ...]


@dataclass(frozen=True)
class MetadataUpdateReport:
    """Result summary of restoring custom metadata fields to a Calibre book."""

    updated_fields: tuple[str, ...]
    failed_fields: tuple[str, ...]

    @property
    def is_success(self) -> bool:
        """Return True if all targeted metadata fields were updated without errors."""
        return len(self.failed_fields) == 0


class CalibreError(OSError):
    """Base exception for all Calibre operations."""


class CalibreConnectionError(CalibreError):
    """Calibre server is unreachable, timed out, or connection refused."""


class CalibreAuthError(CalibreError):
    """HTTP 401/403 authentication error."""


class CalibreConfigurationError(CalibreError):
    """Calibre configuration error (e.g. local directory used without Calibre installed)."""


class CalibreOperationError(CalibreError):
    """Calibre server/database rejected the requested operation."""
