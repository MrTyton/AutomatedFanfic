"""Series/collection URL detection and expansion utility.

This module provides functionality to detect whether a URL points to a series,
collection, or individual story, and to expand series/collection URLs into
lists of individual story URLs using FanFicFare's adapter API.

The module uses the native adapter methods rather than heuristics or regex,
ensuring compatibility with how FanFicFare actually handles list pages.

Key Functions:
    is_series_url: Detect if a URL is a series/collection using adapter methods
    expand_series_url: Extract individual story URLs from a series/collection
    process_url: Unified handler that expands series or passes through stories

Adapter API Usage:
    - Uses get_urls_from_page() for sites that override it (Literotica, FimFiction)
    - Uses get_series_from_page() for AO3 (BaseOTWAdapter)
    - Falls back to treating URL as single story if detection fails
"""

import re
from typing import Any

lazy from fanficfare import adapters, configurable, exceptions, geturls
lazy from config.config_store import ConfigStore
from utils import ff_logging


def _normalize_url(url: str) -> str:
    """Prepend https:// scheme if the URL has no scheme."""
    if url and "://" not in url:
        return "https://" + url
    return url


def _call_get_urls_from_page(
    adapter, url: str, config: configurable.Configuration
) -> dict | None:
    """Invoke adapter.get_urls_from_page, supplying a GetURLs helper when accepted."""
    try:
        gu = geturls.GetURLs(config=config)
        return adapter.get_urls_from_page(url, geturls=gu, normalize=False)
    except TypeError:
        return adapter.get_urls_from_page(url, normalize=False)


def _is_known_series_url_pattern(adapter: Any, url: str) -> bool:
    """Return True if *url* matches a known FanFicFare series URL pattern without HTTP requests.

    Covers:
    - OTW/AO3 sites (``/works/`` in site pattern replaced with ``/series/``)
    - Twisting the Hellmouth (``/Series-<id>``)
    - eFiction sites (``viewseries.php?seriesid=<id>`` / ``series.php?ssid=<id>``)
    """
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
    config_store: Any | None = None,
) -> configurable.Configuration:
    """Build a FanFicFare Configuration for *url* using ConfigStore."""
    if config_store is None:
        config_store = ConfigStore()
    return config_store.get_fff_configuration(url)


def is_series_url(
    url: str,
    config: configurable.Configuration | None = None,
    *,
    config_store: Any | None = None,
) -> bool:
    """
    Determine if a URL points to a series, collection, or single story.

    Uses the FanFicFare adapter's native methods to check if a URL is a list
    type (series/collection) rather than a single story.

    Args:
        url: The fanfiction URL to check
        config: FanFicFare Configuration object (created if not provided)
        config_store: Optional ConfigStore instance

    Returns:
        True if the URL is a series/collection, False if single story or unknown
    """
    url = _normalize_url(url)
    if not config:
        config = get_series_configuration(url, config_store=config_store)

    try:
        # Try to get the adapter for this URL
        adapter = adapters.getAdapter(config, url, anyurl=True)

        # Method 1: Fast zero-network check for known series URL patterns
        # (OTW/AO3, Twisting the Hellmouth, eFiction sites)
        if _is_known_series_url_pattern(adapter, url):
            ff_logging.log_debug(f"Series URL detected: {url}")
            return True

        # Fast-path: if FanFicFare validates the URL as a single story (anyurl=False),
        # never make a network call to scrape the page for list URLs.
        if _is_single_story_url(config, url):
            ff_logging.log_debug(f"Single story URL detected: {url}")
            return False

        # Method 2: Check if this is a site with get_urls_from_page support
        if hasattr(adapter, "get_urls_from_page"):
            try:
                result = _call_get_urls_from_page(adapter, url, config)
                if isinstance(result, dict) and "urllist" in result:
                    urllist = result.get("urllist", [])

                    # Multiple URLs = series/collection
                    # Single URL = single story
                    # Empty = unknown/error
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
    config_store: Any | None = None,
) -> list[str]:
    """
    Extract individual story URLs from a series or collection URL.

    Uses FanFicFare's adapter methods to handle series expansion, including
    pagination and site-specific list extraction.

    Args:
        url: The series/collection URL to expand
        config: FanFicFare Configuration object (created if not provided)
        config_store: Optional ConfigStore instance

    Returns:
        List of individual story URLs extracted from the series.
        Returns empty list if URL is not a series or extraction fails.
    """
    url = _normalize_url(url)
    if not config:
        config = get_series_configuration(url, config_store=config_store)

    try:
        adapter = adapters.getAdapter(config, url, anyurl=True)

        # Fast-path: if FanFicFare validates the URL as a single story (anyurl=False),
        # return [] immediately without making any network calls.
        if _is_single_story_url(config, url):
            return []

        # Method 1: Use adapter's get_series_from_page (OTW/AO3, TtH, eFiction)
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

        # Method 2: Use generic get_urls_from_page (for other sites with list support)
        if hasattr(adapter, "get_urls_from_page"):
            try:
                result = _call_get_urls_from_page(adapter, url, config)
                if isinstance(result, dict) and "urllist" in result:
                    urllist = result.get("urllist", [])
                    if len(urllist) > 1:
                        ff_logging.log(
                            f"Expanded collection URL ({len(urllist)} stories): {url}"
                        )
                        return urllist
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
    config_store: Any | None = None,
) -> dict[str, Any]:
    """
    Unified handler: detect if URL is series and expand or return as single.

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
    result: dict[str, Any] = {
        "is_series": False,
        "urls": [],
        "count": 0,
        "source_url": url,
    }
    if not url:
        result["urls"] = [url]
        result["count"] = 1
        return result

    if not config:
        config = get_series_configuration(url, config_store=config_store)

    try:
        # Cache any _call_get_urls_from_page result during this process_url call
        # so collection URLs are only scraped once across is_series_url + expand_series_url.
        cached_page_res: dict[str, Any] = {}
        orig_call = _call_get_urls_from_page

        def _memoized_call(adapter_obj, target_url, cfg):
            if target_url not in cached_page_res:
                cached_page_res[target_url] = orig_call(adapter_obj, target_url, cfg)
            return cached_page_res[target_url]

        globals()["_call_get_urls_from_page"] = _memoized_call
        try:
            if is_series_url(url, config, config_store=config_store):
                expanded = expand_series_url(url, config, config_store=config_store)
                result["is_series"] = True
                result["urls"] = expanded
                result["count"] = len(expanded)
            else:
                result["urls"] = [url]
                result["count"] = 1
        finally:
            globals()["_call_get_urls_from_page"] = orig_call

    except Exception as e:
        ff_logging.log_debug(f"Error processing URL: {e}")
        result["urls"] = [url]
        result["count"] = 1

    return result
