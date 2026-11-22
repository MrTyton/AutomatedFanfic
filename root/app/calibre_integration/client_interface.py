"""Abstract base class interface and shared helpers for Calibre clients."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import date, datetime
import functools
import re
from urllib.parse import urlsplit

lazy import fanficfare.adapters as fff_adapters

from calibre_integration import calibre_info
from calibre_integration.models import (
    AddedBook,
    BookExport,
    CalibreStorySummary,
    MetadataUpdateReport,
)
from config.store import ConfigStore
from models.fanfic_info import FanficInfo
import ff_logging
from utils import system_utils

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


_EXACT_UPDATE_TAG_RE = re.compile(
    r"^Last Update:\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})$", re.IGNORECASE
)
_YEAR_MONTH_UPDATE_TAG_RE = re.compile(
    r"^Last Update Year/Month:\s*(\d{4})[/-](\d{1,2})$", re.IGNORECASE
)
_SCHEME_PREFIX_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def parse_calibre_update_date(
    tags: list[str], last_modified: datetime | None
) -> tuple[date | None, bool]:
    """Extract the story's last update date from FanFicFare Calibre tags.

    Checks for an exact ``Last Update: YYYY/MM/DD`` tag first, then falls back
    to ``Last Update Year/Month: YYYY/MM`` (using day 1), and finally to
    ``last_modified.date()`` when available.

    Returns:
        Tuple of ``(parsed_date, is_exact)`` where ``is_exact`` is True only
        when derived from an exact ``Last Update:`` tag.
    """
    year_month_fallback: date | None = None

    for tag in tags:
        stripped = tag.strip()
        exact_match = _EXACT_UPDATE_TAG_RE.match(stripped)
        if exact_match:
            try:
                return (
                    date(
                        int(exact_match.group(1)),
                        int(exact_match.group(2)),
                        int(exact_match.group(3)),
                    ),
                    True,
                )
            except ValueError:
                continue

        if year_month_fallback is None:
            ym_match = _YEAR_MONTH_UPDATE_TAG_RE.match(stripped)
            if ym_match:
                try:
                    year_month_fallback = date(
                        int(ym_match.group(1)), int(ym_match.group(2)), 1
                    )
                except ValueError:
                    continue

    if year_month_fallback is not None:
        return (year_month_fallback, False)

    if last_modified is not None:
        return (last_modified.date(), False)

    return (None, False)


def build_site_poll_query(
    site_domain: str,
    include_tags: list[str],
    exclude_tags: list[str],
    override: str = "",
) -> str:
    """Build a Calibre search query for polling in-progress stories on a site.

    When ``override`` is non-empty, returns ``override`` verbatim.
    """
    if override:
        return override

    escaped_domain = site_domain.replace('"', r"\"")
    parts: list[str] = [f'identifiers:"{escaped_domain}"']

    for tag in include_tags:
        clean_tag = tag.strip()
        if clean_tag:
            escaped_tag = clean_tag.replace('"', r"\"")
            parts.append(f'tags:"={escaped_tag}"')

    for tag in exclude_tags:
        clean_tag = tag.strip()
        if clean_tag:
            escaped_tag = clean_tag.replace('"', r"\"")
            parts.append(f'not tags:"={escaped_tag}"')

    return " and ".join(parts)


def _is_valid_story_url(url: str) -> bool:
    """Return True if `url` is a valid HTTP(S) URL or domain-like story URL."""
    if not url or any(ch.isspace() for ch in url):
        return False
    if "://" in url or _SCHEME_PREFIX_RE.match(url):
        parsed = urlsplit(url)
        return parsed.scheme.lower() in ("http", "https") and "." in parsed.netloc
    parsed = urlsplit(f"https://{url}")
    return "." in parsed.netloc and not parsed.netloc.startswith(".")


def _parse_last_modified(raw_value: object) -> datetime | None:
    """Parse a Calibre `last_modified` value (datetime or ISO 8601 string)."""
    if isinstance(raw_value, datetime):
        return raw_value
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if text:
            try:
                return datetime.fromisoformat(text)
            except ValueError:
                return None
    return None


def build_story_summary(
    book_id: str | int, raw: Mapping[str, object]
) -> CalibreStorySummary | None:
    """Build a `CalibreStorySummary` from a raw Calibre book metadata record.

    Returns None (and logs at debug level) if the book has no valid
    HTTP(S) or domain-like `identifiers.url`.
    """
    calibre_id = str(book_id)
    title = str(raw.get("title") or "")

    identifiers = raw.get("identifiers")
    raw_url = identifiers.get("url") if isinstance(identifiers, Mapping) else None
    url = raw_url.strip() if isinstance(raw_url, str) else ""

    if not _is_valid_story_url(url):
        ff_logging.log_debug(
            f"Skipping Calibre book ID {calibre_id} ('{title}'): "
            f"missing or invalid identifiers.url ({raw_url!r})"
        )
        return None

    raw_tags = raw.get("tags")
    tags = (
        [str(t) for t in raw_tags if t is not None]
        if isinstance(raw_tags, list)
        else []
    )
    last_modified = _parse_last_modified(raw.get("last_modified"))
    last_update_date, update_date_exact = parse_calibre_update_date(tags, last_modified)

    return CalibreStorySummary(
        calibre_id=calibre_id,
        title=title,
        url=url,
        tags=tags,
        last_modified=last_modified,
        last_update_date=last_update_date,
        update_date_exact=update_date_exact,
    )


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

    @abstractmethod
    def list_stories_by_query(self, query: str) -> list[CalibreStorySummary]:
        """Return story summaries matching a Calibre search query."""

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
