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

from typing import Optional, Dict, List
from fanficfare import adapters, configurable, exceptions
from utils import ff_logging


def is_series_url(
    url: str, config: Optional[configurable.Configuration] = None
) -> bool:
    """
    Determine if a URL points to a series, collection, or single story.

    Uses the FanFicFare adapter's native methods to check if a URL is a list
    type (series/collection) rather than a single story.

    Args:
        url: The fanfiction URL to check
        config: FanFicFare Configuration object (created if not provided)

    Returns:
        True if the URL is a series/collection, False if single story or unknown
    """
    if not config:
        config = configurable.Configuration(["test.com"], "EPUB", lightweight=True)

    try:
        # Try to get the adapter for this URL
        adapter = adapters.getAdapter(config, url, anyurl=True)

        # Method 1: Check if this is an OTW adapter (AO3) with series support
        if hasattr(adapter, "get_series_from_page"):
            # AO3 has explicit series URL pattern matching
            import re

            # Try to match series pattern: /series/<ID>
            site_pattern = adapter.getSiteURLPattern()
            series_pattern = site_pattern.replace("/works/", "/series/")
            m = re.match(series_pattern, url)
            if m and m.group("id"):
                ff_logging.log_debug(f"Series URL detected (AO3 series): {url}")
                return True

        # Method 2: Check if this is a site with get_urls_from_page override
        if hasattr(adapter, "get_urls_from_page"):
            try:
                result = adapter.get_urls_from_page(url, normalize=False)
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
    url: str, config: Optional[configurable.Configuration] = None
) -> List[str]:
    """
    Extract individual story URLs from a series or collection URL.

    Uses FanFicFare's adapter methods to handle series expansion, including
    pagination and site-specific list extraction.

    Args:
        url: The series/collection URL to expand
        config: FanFicFare Configuration object (created if not provided)

    Returns:
        List of individual story URLs extracted from the series.
        Returns empty list if URL is not a series or extraction fails.
    """
    if not config:
        config = configurable.Configuration(["test.com"], "EPUB", lightweight=True)

    try:
        adapter = adapters.getAdapter(config, url, anyurl=True)

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
                result = adapter.get_urls_from_page(url, normalize=False)
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
    url: str, config: Optional[configurable.Configuration] = None
) -> Dict[str, any]:
    """
    Unified handler: detect if URL is series and expand or return as single.

    This is the primary interface for processing URLs in the ingestion pipeline.
    It handles both individual stories and series/collections transparently.

    Args:
        url: The fanfiction URL to process
        config: FanFicFare Configuration object (created if not provided)

    Returns:
        Dictionary with:
            - 'is_series': bool indicating if URL was a series
            - 'urls': list of URLs (multiple if series, single if story)
            - 'count': number of URLs returned
            - 'source_url': original URL
    """
    if not config:
        config = configurable.Configuration(["test.com"], "EPUB", lightweight=True)

    result = {"is_series": False, "urls": [], "count": 0, "source_url": url}

    try:
        if is_series_url(url, config):
            # Expand the series URL
            expanded = expand_series_url(url, config)
            if expanded:
                result["is_series"] = True
                result["urls"] = expanded
                result["count"] = len(expanded)
                return result

        # If not a series or expansion failed, treat as single story
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
