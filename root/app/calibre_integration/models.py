"""Domain models and exceptions for Calibre operations."""

from dataclasses import dataclass
from datetime import date, datetime
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


@dataclass(frozen=True)
class CalibreStorySummary:
    """Summary metadata for a Calibre story returned by bulk query listing."""

    calibre_id: str
    title: str
    url: str
    tags: list[str]
    last_modified: datetime | None
    last_update_date: date | None
    update_date_exact: bool


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
