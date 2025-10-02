"""Automatic URL parser generation from FanFicFare adapters.

This module provides dynamic URL pattern generation by extracting site examples
from FanFicFare adapters, eliminating the need for manual maintenance of URL
parsing patterns. It creates regex patterns and URL prefixes for fanfiction
site recognition and URL normalization.

Key Features:
    - Automatic pattern generation from FanFicFare adapter examples
    - Site-specific URL parsing rules and regex patterns
    - Domain normalization and URL prefix generation
    - Forum site support with thread-specific patterns
    - Fallback pattern for unrecognized URLs
    - Error handling for invalid regex patterns

Functions:
    generate_url_parsers_from_fanficfare: Main parser generation function
    _generate_pattern_and_prefix: Creates site-specific regex patterns
    _generate_site_identifier: Generates meaningful site identifiers

Global Variables:
    url_parsers: Dictionary of compiled regex patterns and URL prefixes

Architecture:
    The module analyzes FanFicFare adapter examples to understand URL structures
    and generates appropriate regex patterns for each site. It handles special
    cases for major sites and provides sensible defaults for others.

Example:
    >>> from auto_url_parsers import url_parsers
    >>> pattern, prefix = url_parsers['ffnet']
    >>> match = pattern.search("https://www.fanfiction.net/s/12345/1/story")
"""

import re
import fanficfare.adapters as adapters
from urllib.parse import urlparse
from typing import Dict, Tuple


def generate_url_parsers_from_fanficfare() -> Dict[str, Tuple[re.Pattern, str]]:
    """Generates URL parsers dictionary from FanFicFare adapters automatically.

    Extracts site examples from FanFicFare adapters and creates regex patterns
    for URL parsing and normalization. Processes each adapter's example URLs
    to generate appropriate regex patterns and URL prefixes for site identification
    and canonical URL reconstruction.

    The function handles various site types including story sites (FanFiction.Net,
    Archive of Our Own), forum sites (SpaceBattles, SufficientVelocity), and
    other fanfiction platforms. It applies site-specific rules for URL structure
    and provides fallback patterns for unrecognized sites.

    Returns:
        Dict[str, Tuple[re.Pattern, str]]: Dictionary mapping site identifiers
            to tuples containing:
            - re.Pattern: Compiled regex pattern for matching and extracting URLs
            - str: URL prefix for reconstructing canonical URLs

    Note:
        Invalid regex patterns are caught and logged as warnings, but do not
        prevent the function from completing. A fallback "other" pattern is
        always included for unrecognized URLs.

    Example:
        >>> parsers = generate_url_parsers_from_fanficfare()
        >>> ffnet_pattern, ffnet_prefix = parsers['ffnet']
        >>> match = ffnet_pattern.search("https://www.fanfiction.net/s/12345/1/")
    """
    # Get site examples from FanFicFare adapter registry
    examples = adapters.getSiteExamples()
    url_parsers = {}

    for site, urls in examples:
        # Skip sites without example URLs
        if not urls:
            continue

        # Use the first URL as the pattern base for analysis
        first_url = urls[0]
        parsed = urlparse(first_url)
        domain = parsed.netloc
        path = parsed.path
        query = parsed.query

        # Create meaningful site identifier from domain
        site_id = _generate_site_identifier(domain, site)

        # Generate regex pattern and URL prefix using algorithmic rules
        pattern, prefix = _generate_pattern_and_prefix(domain, path, query)

        try:
            # Compile and validate the regex pattern
            compiled_pattern = re.compile(pattern)
            url_parsers[site_id] = (compiled_pattern, prefix)
        except re.error as e:
            # Log compilation failures and skip invalid patterns
            print(f"Warning: Failed to compile regex for {site}: {e}")
            continue

    # Add fallback pattern for any unrecognized URLs
    url_parsers["other"] = (re.compile(r"https?://(.*)"), "")

    return url_parsers


def _generate_pattern_and_prefix(domain: str, path: str, query: str) -> Tuple[str, str]:
    """Generates regex pattern and URL prefix for a given domain and path structure.

    Creates a regex pattern that can match story URLs from a specific fanfiction
    site and determines the appropriate URL prefix for reconstructing canonical
    URLs. Applies site-specific rules based on domain characteristics and URL
    structure patterns to handle various fanfiction site architectures.

    Args:
        domain (str): The domain name from the example URL (e.g., 'www.fanfiction.net').
                     Used to determine site type and URL structure rules.
        path (str): The URL path component (e.g., '/s/12345/1/Story-Title').
                   Analyzed to identify story ID patterns and site structure.
        query (str): The query string component (e.g., 'chapter=1').
                    Processed for sites that use query parameters for navigation.

    Returns:
        Tuple[str, str]: A tuple containing:
            - regex_pattern (str): Regex pattern string for matching URLs with
              appropriate capture groups for URL reconstruction
            - url_prefix (str): Base domain prefix for reconstructing canonical
              URLs, with appropriate www handling

    Note:
        The function handles special cases for major sites like FanFiction.Net,
        Archive of Our Own, and forum sites. It normalizes www prefixes and
        creates capture groups for efficient URL processing.

    Example:
        >>> pattern, prefix = _generate_pattern_and_prefix(
        ...     "www.fanfiction.net", "/s/12345/1/Story", ""
        ... )
        >>> # Returns pattern for capturing /s/ID and prefix "www.fanfiction.net"
    """
    # Analyze domain characteristics for rule application
    is_forum_site = "forum" in domain or "threads" in path
    has_www = domain.startswith("www.")
    is_fanfiction_net = "fanfiction.net" in domain

    # Clean domain for pattern matching (remove www. prefix if present)
    clean_domain = domain[4:] if has_www else domain

    # Build the core path pattern based on site type and structure
    if is_forum_site:
        # For forums: match threads up to the thread ID for proper extraction
        if "/threads/" in path:
            path_pattern = r"/threads/[^/]*\.\d+"
        else:
            # Generic forum pattern with escaped special characters
            path_pattern = re.escape(path)
            path_pattern = re.sub(r"\\d+", r"\\d+", path_pattern)
    else:
        # For story sites: match the core story pattern based on URL structure
        if "/s/" in path:  # FanFiction.Net/FictionPress style URLs
            path_pattern = r"/s/\d+"
        elif "/works/" in path:  # Archive of Our Own style URLs
            path_pattern = r"/works/\d+"
        elif "/fiction/" in path:  # RoyalRoad style URLs
            path_pattern = r"/fiction/\d+"
        else:
            # Generic pattern: escape special characters and replace number sequences
            path_pattern = re.escape(path)
            path_pattern = re.sub(r"\\d+", r"\\d+", path_pattern)

    # Build query pattern component if query parameters are present
    query_part = ""
    if query:
        query_escaped = re.escape(query)
        # Replace escaped digit sequences with regex digit patterns
        query_pattern = re.sub(r"\\d+", r"\\d+", query_escaped)
        query_part = f"\\?{query_pattern}"

    # Apply site-specific rules for capture groups and URL prefixes
    if is_fanfiction_net:
        # Special case: FanFiction.Net always gets www. prefix and captures path only
        # Create pattern for URLs with/without chapter info
        domain_pattern = f"(?:www\\.)?{re.escape(clean_domain)}"

        # Pattern that captures /s/ID/ for URLs with chapter info
        pattern_with_chapter = f"https?://{domain_pattern}(/s/\\d+)/\\d+.*"
        # Pattern that captures /s/ID for URLs without chapter info
        pattern_without_chapter = f"https?://{domain_pattern}(/s/\\d+)/?$"

        # Combine both patterns for comprehensive matching
        pattern = f"(?:{pattern_with_chapter}|{pattern_without_chapter})"
        prefix = f"www.{clean_domain}"
    elif is_forum_site:
        # Forum sites: capture domain + essential path, strip trailing content
        domain_pattern = re.escape(domain)
        pattern = f"https?://{domain_pattern}({path_pattern})/?.*"
        prefix = domain
    elif has_www:
        # Sites with www: remove www from captured URL, capture path only
        domain_pattern = f"(?:www\\.)?{re.escape(clean_domain)}"
        pattern = f"https?://{domain_pattern}({path_pattern}{query_part})/?.*"
        prefix = clean_domain
    else:
        # Sites without www: capture full domain + path for reconstruction
        domain_pattern = re.escape(domain)
        pattern = f"https?://({domain_pattern}{path_pattern}{query_part})/?.*"
        prefix = ""

    return pattern, prefix


def _generate_site_identifier(domain: str, site: str) -> str:
    """Generates a meaningful site identifier from the domain algorithmically.

    Creates a concise, meaningful identifier for a fanfiction site based on
    its domain name. Uses algorithmic rules to extract the most significant
    part of the domain while handling common prefixes and domain structures.

    Args:
        domain (str): The full domain name (e.g., 'www.fanfiction.net',
                     'forums.spacebattles.com', 'archiveofourown.org').
        site (str): The original site name from FanFicFare (used as fallback).

    Returns:
        str: A concise site identifier suitable for use as a dictionary key
             (e.g., 'fanfiction', 'spacebattles', 'archiveofourown').

    Example:
        >>> _generate_site_identifier('www.fanfiction.net', 'fanfiction.net')
        'fanfiction'
        >>> _generate_site_identifier('forums.spacebattles.com', 'spacebattles.com')
        'spacebattles'
    """
    # Use algorithmic approach - split domain into components
    parts = domain.split(".")
    if len(parts) >= 2:
        # Skip common prefixes that don't identify the site
        if parts[0] in ["www", "forums", "archive", "forum"]:
            # Use the main domain part (second component if available)
            return parts[1] if len(parts) > 2 else parts[0]
        else:
            # Use the first part as the primary identifier
            return parts[0]

    # Fallback: sanitize the original site name for use as identifier
    return site.lower().replace(".", "_").replace("-", "_")


# Note: URL parsers are no longer automatically generated at module import.
# Call generate_url_parsers_from_fanficfare() explicitly when needed.

# Generate the parsers when running as script for testing/debugging
if __name__ == "__main__":
    url_parsers = generate_url_parsers_from_fanficfare()
    print(f"Auto-generated {len(url_parsers)} URL parsers from FanFicFare adapters")

    # Show some key parsers for verification
    key_sites = ["ffnet", "ao3", "sb", "sv", "qq", "royalroad"]
    print("\nKey site parsers:")
    for site in key_sites:
        if site in url_parsers:
            pattern, prefix = url_parsers[site]
            print(f"  {site:12} -> {pattern.pattern}")
            if prefix:
                print(f"               Prefix: {prefix}")
