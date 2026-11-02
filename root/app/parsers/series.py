"""Series and collection URL detection and expansion using FanFicFare adapters."""

import re
from typing import Protocol, TypedDict

lazy from config.store import ConfigStore
lazy from fanficfare import adapters, configurable, exceptions, geturls
import ff_logging
from parsers.regex_parsing import normalize_url as _normalize_url

__all__ = [
    "FanFicFareAdapter",
    "SeriesExpansionResult",
    "expand_series_url",
    "get_series_configuration",
    "is_series_url",
    "process_url",
]


class SeriesExpansionResult(TypedDict):
    is_series: bool
    urls: list[str]
    count: int
    source_url: str | None


class FanFicFareAdapter(Protocol):
    """Structural protocol for FanFicFare adapter objects used in series detection."""

    def getSiteURLPattern(self) -> str: ...
    def get_urls_from_page(
        self, url: str, /, **kwargs: object
    ) -> dict[str, object]: ...
    def get_series_from_page(
        self, url: str, data: object, /, **kwargs: object
    ) -> dict[str, object]: ...
    def get_request(self, url: str) -> object: ...


def _call_get_urls_from_page(
    adapter: FanFicFareAdapter,
    url: str,
    config: configurable.Configuration,
    _page_cache: dict[str, dict[str, object] | None] | None = None,
) -> dict[str, object] | None:
    """Invoke adapter.get_urls_from_page, supplying a GetURLs helper when accepted."""
    if _page_cache is not None and url in _page_cache:
        return _page_cache[url]
    try:
        gu = geturls.GetURLs(config=config)
        res = adapter.get_urls_from_page(url, geturls=gu, normalize=False)
    except TypeError:
        res = adapter.get_urls_from_page(url, normalize=False)
    if _page_cache is not None:
        _page_cache[url] = res
    return res


def _is_known_series_url_pattern(adapter: FanFicFareAdapter, url: str) -> bool:
    """Return True if *url* matches a known FanFicFare series URL pattern without HTTP requests."""
    site_pattern = (
        adapter.getSiteURLPattern() if hasattr(adapter, "getSiteURLPattern") else None
    )
    if isinstance(site_pattern, str) and "/works/" in site_pattern:
        series_pattern = site_pattern.replace("/works/", "/series/")
        m = re.match(series_pattern, url)
        if m and m.group("id"):
            return True

    # Twisting the Hellmouth (adapter_tthfanficorg.py)
    if re.match(r"https?://(?:www\.)?tthfanfic\.org/Series-(?P<id>\d+)", url):
        return True

    # eFiction sites (base_adapter.py get_series_from_page)
    if re.match(r".*(?:view)?series\.php\?s(?:erie)?sid=\d+.*", url):
        return True

    return False


def _is_single_story_url(config: configurable.Configuration, url: str) -> bool:
    """Return True if *url* is accepted by FanFicFare as a single-story URL."""
    try:
        adapter = adapters.getAdapter(config, url, anyurl=False)
        if _is_known_series_url_pattern(adapter, url):
            return False
        return True
    except Exception:
        return False


def get_series_configuration(
    url: str,
    config_store: ConfigStore | None = None,
) -> configurable.Configuration:
    """Build a FanFicFare Configuration for *url* using ConfigStore."""
    if config_store is None:
        config_store = ConfigStore({})
    return config_store.get_fff_configuration(url)


def is_series_url(
    url: str,
    config: configurable.Configuration | None = None,
    *,
    config_store: ConfigStore | None = None,
    _page_cache: dict[str, dict[str, object] | None] | None = None,
) -> bool:
    """Determine if a URL points to a series, collection, or single story.

    Uses the FanFicFare adapter's native methods to check if a URL is a list
    type (series/collection) rather than a single story.

    Args:
        url: The fanfiction URL to check
        config: FanFicFare Configuration object (created if not provided)
        config_store: Optional ConfigStore instance
        _page_cache: Optional per-call cache dict for get_urls_from_page results

    Returns:
        True if the URL is a series/collection, False if single story or unknown
    """
    url = _normalize_url(url)
    if not config:
        config = get_series_configuration(url, config_store=config_store)

    try:
        adapter = adapters.getAdapter(config, url, anyurl=True)

        if _is_known_series_url_pattern(adapter, url):
            ff_logging.log_debug(f"Series URL detected: {url}")
            return True

        if _is_single_story_url(config, url):
            ff_logging.log_debug(f"Single story URL detected: {url}")
            return False

        if hasattr(adapter, "get_urls_from_page"):
            try:
                result = _call_get_urls_from_page(
                    adapter, url, config, _page_cache=_page_cache
                )
                if isinstance(result, dict) and "urllist" in result:
                    urllist = result.get("urllist", [])
                    if isinstance(urllist, list):
                        if len(urllist) > 1:
                            ff_logging.log_debug(
                                f"Series/collection URL detected ({len(urllist)} stories): {url}"
                            )
                            return True
                        elif len(urllist) == 1:
                            ff_logging.log_debug(f"Single story URL detected: {url}")
                            return False
            except Exception as e:
                ff_logging.log_debug(f"Error checking series status: {e}")

        return False

    except (exceptions.UnknownSite, Exception) as e:
        ff_logging.log_debug(
            f"Could not determine if URL is series (treating as single): {e}"
        )
        return False


def expand_series_url(
    url: str,
    config: configurable.Configuration | None = None,
    *,
    config_store: ConfigStore | None = None,
    _page_cache: dict[str, dict[str, object] | None] | None = None,
) -> list[str]:
    """Extract individual story URLs from a series or collection URL.

    Uses FanFicFare's adapter methods to handle series expansion, including
    pagination and site-specific list extraction.

    Args:
        url: The series/collection URL to expand
        config: FanFicFare Configuration object (created if not provided)
        config_store: Optional ConfigStore instance
        _page_cache: Optional per-call cache dict for get_urls_from_page results

    Returns:
        List of individual story URLs extracted from the series.
        Returns empty list if URL is not a series or extraction fails.
    """
    url = _normalize_url(url)
    if not config:
        config = get_series_configuration(url, config_store=config_store)

    try:
        adapter = adapters.getAdapter(config, url, anyurl=True)

        if _is_single_story_url(config, url):
            return []

        if hasattr(adapter, "get_series_from_page") and _is_known_series_url_pattern(
            adapter, url
        ):
            try:
                data = adapter.get_request(url)
                gu = geturls.GetURLs(config=config)
                try:
                    result = adapter.get_series_from_page(
                        url, data, normalize=False, geturls=gu
                    )
                except TypeError:
                    result = adapter.get_series_from_page(url, data, normalize=False)

                if isinstance(result, dict) and "urllist" in result:
                    urllist = result.get("urllist", [])
                    if urllist:
                        ff_logging.log(
                            f"Expanded series URL ({len(urllist)} stories): {url}"
                        )
                        return urllist
            except Exception as e:
                ff_logging.log_debug(f"Error in get_series_from_page: {e}")

        if hasattr(adapter, "get_urls_from_page"):
            try:
                result = _call_get_urls_from_page(
                    adapter, url, config, _page_cache=_page_cache
                )
                if isinstance(result, dict) and "urllist" in result:
                    urllist = result.get("urllist", [])
                    if isinstance(urllist, list) and len(urllist) > 1:
                        ff_logging.log(
                            f"Expanded collection URL ({len(urllist)} stories): {url}"
                        )
                        return [str(u) for u in urllist]
            except Exception as e:
                ff_logging.log_debug(f"Error in get_urls_from_page: {e}")

        return []

    except (exceptions.UnknownSite, Exception) as e:
        ff_logging.log_debug(f"Could not expand series URL: {e}")
        return []


def process_url(
    url: str | None,
    config: configurable.Configuration | None = None,
    *,
    config_store: ConfigStore | None = None,
) -> SeriesExpansionResult:
    """Unified handler: detect if URL is series and expand or return as single.

    This is the primary interface for processing URLs in the ingestion pipeline.
    It handles both individual stories and series/collections transparently, and
    caches any collection page scrape so ``get_urls_from_page`` is never invoked
    twice over HTTP during the same ``process_url`` call.

    Args:
        url: The fanfiction URL to process
        config: FanFicFare Configuration object (created if not provided)
        config_store: Optional ConfigStore instance

    Returns:
        Dictionary with:
            - 'is_series': bool indicating if URL was a series
            - 'urls': list of URLs (multiple if series, single if story)
            - 'count': number of URLs returned
            - 'source_url': original URL
    """
    result: SeriesExpansionResult = {
        "is_series": False,
        "urls": [],
        "count": 0,
        "source_url": url,
    }
    if not url:
        result["urls"] = [url] if url is not None else []
        result["count"] = len(result["urls"])
        return result

    if not config:
        config = get_series_configuration(url, config_store=config_store)

    try:
        page_cache: dict[str, dict[str, object] | None] = {}
        if is_series_url(
            url, config, config_store=config_store, _page_cache=page_cache
        ):
            expanded = expand_series_url(
                url, config, config_store=config_store, _page_cache=page_cache
            )
            result["is_series"] = True
            result["urls"] = expanded
            result["count"] = len(expanded)
        else:
            result["urls"] = [url]
            result["count"] = 1

    except Exception as e:
        ff_logging.log_debug(f"Error processing URL: {e}")
        result["urls"] = [url]
        result["count"] = 1

    return result
