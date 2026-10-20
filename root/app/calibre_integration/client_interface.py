"""Abstract base class interface and shared helpers for Calibre clients."""

from abc import ABC, abstractmethod
from typing import Any

from calibre_integration import calibre_info
from calibre_integration.models import AddedBook, BookExport, MetadataUpdateReport
from config.config_store import ConfigStore
from models.fanfic_info import FanficInfo
from utils import ff_logging, system_utils


def build_url_search_query(url: str) -> str:
    """Build an exact-match Calibre search query for a story URL.

    FanFicFare writes `<dc:identifier opf:scheme="URL">https://...</dc:identifier>`
    (EPUB 2, stored under `identifiers:url` or `identifiers:uri` when used as the
    package `unique-identifier`) or `<dc:identifier>URL:https://...</dc:identifier>`
    (EPUB 3, stored under `identifiers:url`). Searching `identifiers:":=value"`
    performs an exact value match across any identifier key (preventing prefix URL
    collisions like `/works/123` vs `/works/1234`), while `identifiers:{scheme}:="rest"`
    covers older books where an unprefixed URL was split on the scheme colon.

    Args:
        url: The story URL to search for.

    Returns:
        str: Calibre search expression matching exact identifier values.
    """
    escaped_url = url.replace("\\", "\\\\").replace('"', r"\"")
    if ":" in url:
        scheme, rest = url.split(":", 1)
        escaped_rest = rest.replace("\\", "\\\\").replace('"', r"\"")
        return (
            f'identifiers:":={escaped_url}" or identifiers:{scheme}:="{escaped_rest}"'
        )
    return f'identifiers:":={escaped_url}"'


class CalibreClient(ABC):
    """Common interface for interacting with Calibre databases and Content Servers."""

    def __init__(
        self,
        cdb_info: calibre_info.CalibreInfo,
        config_store: ConfigStore,
    ) -> None:
        """Initialize the Calibre client.

        Args:
            cdb_info: Configuration object containing library path/URL, credentials, and lock.
            config_store: Shared ConfigStore instance for hot-reloading Calibre settings.
        """
        self.cdb_info = cdb_info
        self._config_store = config_store

    def set_config_store(self, config_store: ConfigStore) -> None:
        """Attach a ConfigStore so Calibre settings are refreshed before each call."""
        self._config_store = config_store

    def refresh_if_changed(self) -> None:
        """Sync cdb_info from ConfigStore if any Calibre field changed."""
        if self._config_store is not None:
            if self.cdb_info.update_from_config_store(self._config_store):
                self._on_config_refreshed()

    def _on_config_refreshed(self) -> None:
        """Hook invoked when `cdb_info` is updated from `ConfigStore`."""

    @abstractmethod
    def get_story_id(self, fanfic: FanficInfo) -> str | None:
        """Retrieve Calibre book ID by matching identifiers, or None."""

    @abstractmethod
    def add_story(self, location: str, fanfic: FanficInfo) -> AddedBook | None:
        """Add an EPUB to Calibre and return the added book record."""

    @abstractmethod
    def remove_story(self, fanfic: FanficInfo) -> bool:
        """Remove a story from Calibre by ID."""

    @abstractmethod
    def export_story(self, fanfic: FanficInfo, location: str) -> BookExport | None:
        """Export an EPUB story to target location and return its export record."""

    @abstractmethod
    def add_format_to_existing_story(self, location: str, fanfic: FanficInfo) -> bool:
        """Replace EPUB format for an existing story without modifying metadata."""

    @abstractmethod
    def get_metadata(self, fanfic: FanficInfo) -> dict[str, Any]:
        """Fetch all metadata fields for a story."""

    @abstractmethod
    def set_metadata_fields(
        self,
        fanfic: FanficInfo,
        metadata: dict[str, Any],
    ) -> MetadataUpdateReport:
        """Restore custom metadata fields for a story."""

    @abstractmethod
    def get_version(self) -> str:
        """Return the Calibre version string."""

    def log_metadata_comparison(
        self,
        fanfic: FanficInfo,
        old_metadata: dict[str, Any] | None,
        new_metadata: dict[str, Any] | None,
    ) -> None:
        """Log comparison of metadata (helper method)."""
        old_meta = old_metadata or {}
        new_meta = new_metadata or {}
        if not old_meta and not new_meta:
            return

        ff_logging.log_debug(f"\t({fanfic.site}) Metadata Comparison Report")

        changed = []
        lost = []

        for field, old_val in old_meta.items():
            if field in new_meta:
                new_val = new_meta[field]
                if old_val != new_val:
                    changed.append((field, str(old_val)[:50], str(new_val)[:50]))
            else:
                lost.append(field)

        new_fields = [k for k in new_meta.keys() if k not in old_meta]

        if changed:
            ff_logging.log_debug(f"\t  Fields Changed: {len(changed)}")
            for field, old_val, new_val in changed:
                ff_logging.log_debug(f"\t    ~ {field}: '{old_val}' → '{new_val}'")

        if lost:
            ff_logging.log_debug(f"\t  Fields Lost: {len(lost)}")
            for field in lost:
                ff_logging.log_debug(f"\t    ✗ {field}")

        if new_fields:
            ff_logging.log_debug(f"\t  New Fields Added: {len(new_fields)}")
            for field in new_fields:
                ff_logging.log_debug(f"\t    + {field}")

    def _find_epub_in_directory(self, location: str) -> str | None:
        """Helper to find first EPUB in directory."""
        try:
            epub_files = system_utils.get_files(
                location, file_extension="epub", return_full_path=True
            )
            return epub_files[0] if epub_files else None
        except OSError:
            return None
