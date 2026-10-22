"""Abstract base class interface and shared helpers for Calibre clients."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
import functools
import re
from urllib.parse import urlsplit

lazy import fanficfare.adapters as fff_adapters

from calibre_integration import calibre_info
from calibre_integration.models import AddedBook, BookExport, MetadataUpdateReport
from config.config_store import ConfigStore
from models.fanfic_info import FanficInfo
from utils import ff_logging, system_utils

# Calibre metadata is a dict with dynamic string keys from the Calibre JSON API.
# Values may be scalars, lists, or nested dicts, so we use `object` as the value type.
CalibreMetadata = Mapping[str, object]


@functools.lru_cache(maxsize=1024)
def extract_story_base_url(url: str) -> str:
    """Normalize a fanfiction URL to its canonical domain and story base path.

    Resolves chapter/page links via FanFicFare adapters, strips scheme and
    subdomain prefixes (www, m), and removes optional title slugs.
    """
    clean = url.strip().split("#")[0]
    if not clean:
        return ""

    probe_url = clean if "://" in clean else f"https://{clean}"
    try:
        norm = fff_adapters.getNormalStoryURL(probe_url)
        if norm:
            clean = norm
    except Exception:
        clean = probe_url

    parsed = urlsplit(clean)
    netloc = re.sub(r"^(www\d*|m|mobi)\.", "", parsed.netloc, flags=re.IGNORECASE)

    # Path segments without empty strings
    segments = [s for s in parsed.path.strip("/").split("/") if s]

    # Strip trailing title slug (alphabetic text following a numeric ID or chapter)
    if (
        len(segments) >= 2
        and re.search(r"[a-zA-Z]", segments[-1])
        and segments[-2].isdigit()
    ):
        segments.pop()

    # Strip embedded title slug in XenForo-style segments (<slug>.<numeric_id>)
    if segments and "/threads" in parsed.path:
        segments[-1] = re.sub(r"^.+\.(\d+)$", r"\1", segments[-1])

    base_path = f"/{'/'.join(segments)}" if segments else ""
    if parsed.query and not segments:
        base_path = f"?{parsed.query}"
    elif parsed.query:
        m_id = re.search(
            r"(?:sid|storyid|bid|id)=\d+", parsed.query, flags=re.IGNORECASE
        )
        if m_id and not any(s.isdigit() for s in segments):
            base_path += f"?{m_id.group(0)}"

    return f"{netloc}{base_path}"


def build_url_search_query(url: str) -> str:
    """Build an anchored regex Calibre search query for a story URL.

    Uses Calibre's native regular expression search operator ('~') on the
    'identifiers' field. Matches across schemes ('http://', 'https://'),
    common subdomains ('www.', 'm.'), title slugs, and chapter subpaths, while
    anchoring on URL delimiters ('/', '&', '?', '#') or end-of-string to strictly
    prevent numeric prefix collisions (e.g. '/works/123' matching '/works/1234').

    Args:
        url: The story URL to search for.

    Returns:
        str: Calibre search expression matching identifier regex pattern.
    """
    base = extract_story_base_url(url)

    # For forum thread URLs (/threads/<id>), allow optional title slugs before the id
    if "/threads/" in base:
        parts = base.split("/threads/")
        escaped_domain = re.escape(parts[0])
        escaped_id = re.escape(parts[1])
        pattern = f"{escaped_domain}/threads/(.*\\.)?{escaped_id}"
    else:
        pattern = re.escape(base)

    pattern = pattern.replace('"', r"\"")
    return f'identifiers:"~(//|^)(www\\d*\\.|m\\.)?{pattern}([/&?#].*)?$"'


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
    def get_metadata(self, fanfic: FanficInfo) -> CalibreMetadata:
        """Fetch all metadata fields for a story."""

    @abstractmethod
    def set_metadata_fields(
        self,
        fanfic: FanficInfo,
        metadata: CalibreMetadata,
    ) -> MetadataUpdateReport:
        """Restore custom metadata fields for a story."""

    @abstractmethod
    def get_version(self) -> str:
        """Return the Calibre version string."""

    def log_metadata_comparison(
        self,
        fanfic: FanficInfo,
        old_metadata: CalibreMetadata | None,
        new_metadata: CalibreMetadata | None,
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
