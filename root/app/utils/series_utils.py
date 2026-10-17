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


def _is_single_story_url(config: configurable.Configuration, url: str) -> bool:
    """Return True if *url* is accepted by FanFicFare as a single-story URL."""
    if "/series/" in url.lower():
        return False
    try:
        adapters.getAdapter(config, url, anyurl=False)
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

        # Method 1: Check if this is an OTW adapter (AO3) with series support
        if hasattr(adapter, "get_series_from_page"):
            # Try to match series pattern: /series/<ID>
            site_pattern = (
                adapter.getSiteURLPattern()
                if hasattr(adapter, "getSiteURLPattern")
                else None
            )
            if isinstance(site_pattern, str) and "/works/" in site_pattern:
                series_pattern = site_pattern.replace("/works/", "/series/")
                m = re.match(series_pattern, url)
                if m and m.group("id"):
                    ff_logging.log_debug(f"Series URL detected (AO3 series): {url}")
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

        # Method 1: Use AO3's native get_series_from_page (handles pagination)
        if hasattr(adapter, "get_series_from_page"):
            try:
                # First, we need to fetch the page data
                data = adapter.get_request(url)

                # Then parse it for series URLs
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
    It handles both individual stories and series/collections transparently.

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
    if not config and url:
        config = get_series_configuration(url, config_store=config_store)

    result = {"is_series": False, "urls": [], "count": 0, "source_url": url}

    try:
        if url and is_series_url(
            url,
            config,
            config_store=config_store,
        ):
            # Expand the series URL
            expanded = expand_series_url(
                url,
                config,
                config_store=config_store,
            )
            if expanded:
                result["is_series"] = True
                result["urls"] = expanded
                result["count"] = len(expanded)
                return result
            else:
                # Detected as series, but expansion returned 0 stories (e.g. error)
                result["is_series"] = True
                result["urls"] = []
                result["count"] = 0
                return result

        # If not a series, treat as single story
        result["is_series"] = False
        result["urls"] = [url]
        result["count"] = 1
        return result

    except Exception as e:
        ff_logging.log_debug(f"Error processing URL: {e}")
        # Failsafe: return original URL as single story
        result["urls"] = [url]
        result["count"] = 1
        return result
