"""Automatic URL pattern and parser generation from FanFicFare adapters."""

from __future__ import annotations

import functools
import re
from urllib.parse import urlparse

lazy import fanficfare.adapters as adapters


@functools.lru_cache(maxsize=1)
def generate_url_parsers_from_fanficfare() -> dict[str, tuple[re.Pattern, str]]:
    """Generate URL parsers dictionary from FanFicFare adapters automatically.

    Extracts site examples from FanFicFare adapters and creates regex patterns
    for URL parsing and normalization.

    Returns:
        Dict mapping site identifiers to tuples containing:
            - re.Pattern: Compiled regex pattern for matching and extracting URLs
            - str: URL prefix for reconstructing canonical URLs
    """
    examples = adapters.getSiteExamples()
    url_parsers: dict[str, tuple[re.Pattern, str]] = {}

    for site, urls in examples:
        if not urls:
            continue

        first_url = urls[0]
        parsed = urlparse(first_url)
        domain = parsed.netloc
        path = parsed.path
        query = parsed.query

        site_id = _generate_site_identifier(domain, site)
        pattern, prefix = _generate_pattern_and_prefix(domain, path, query)

        try:
            compiled_pattern = re.compile(pattern)
            url_parsers[site_id] = (compiled_pattern, prefix)
        except re.error as e:
            print(f"Warning: Failed to compile regex for {site}: {e}")
            continue

    url_parsers["other"] = (re.compile(r"https?://(.*)"), "")
    return url_parsers


def _generate_pattern_and_prefix(domain: str, path: str, query: str) -> tuple[str, str]:
    """Generate regex pattern and URL prefix for a given domain and path structure."""
    is_forum_site = "forum" in domain or "threads" in path
    has_www = domain.startswith("www.")
    is_fanfiction_net = "fanfiction.net" in domain

    clean_domain = domain[4:] if has_www else domain

    if is_forum_site:
        if "/threads/" in path:
            path_pattern = r"/threads/[^/]*\.\d+"
        else:
            path_pattern = re.escape(path)
            path_pattern = re.sub(r"\d+", r"\\d+", path_pattern)
    else:
        if "/s/" in path:
            path_pattern = r"/s/\d+"
        elif "/works/" in path:
            path_pattern = r"/(?:works|series)/\d+"
        elif "/fiction/" in path:
            path_pattern = r"/fiction/\d+"
        elif "/series/" in path:
            path_pattern = r"/series/\d+"
        else:
            path_pattern = re.escape(path)
            path_pattern = re.sub(r"\d+", r"\\d+", path_pattern)

    query_part = ""
    if query:
        query_escaped = re.escape(query)
        query_pattern = re.sub(r"\d+", r"\\d+", query_escaped)
        query_part = f"\\?{query_pattern}"

    if is_fanfiction_net:
        domain_pattern = f"(?:www\\.)?{re.escape(clean_domain)}"
        pattern_with_chapter = f"https?://{domain_pattern}(/s/\\d+/\\d+/?).*"
        pattern_without_chapter = f"https?://{domain_pattern}(/s/\\d+)/?$"
        pattern = f"(?:{pattern_with_chapter}|{pattern_without_chapter})"
        prefix = f"www.{clean_domain}"
    elif is_forum_site:
        domain_pattern = re.escape(domain)
        pattern = f"https?://{domain_pattern}({path_pattern})/?.*"
        prefix = domain
    elif has_www:
        domain_pattern = f"(?:www\\.)?{re.escape(clean_domain)}"
        pattern = f"https?://{domain_pattern}({path_pattern}{query_part})/?.*"
        prefix = clean_domain
    else:
        domain_pattern = re.escape(domain)
        pattern = f"https?://({domain_pattern}{path_pattern}{query_part})/?.*"
        prefix = ""

    return pattern, prefix


def _generate_site_identifier(domain: str, site: str) -> str:
    """Generate a concise, meaningful site identifier from a domain."""
    parts = domain.split(".")
    if len(parts) >= 2:
        if parts[0] in ["www", "forums", "archive", "forum"]:
            return parts[1] if len(parts) > 2 else parts[0]
        return parts[0]

    return site.lower().replace(".", "_").replace("-", "_")


if __name__ == "__main__":
    url_parsers = generate_url_parsers_from_fanficfare()
    print(f"Auto-generated {len(url_parsers)} URL parsers from FanFicFare adapters")

    key_sites = ["ffnet", "ao3", "sb", "sv", "qq", "royalroad"]
    print("\nKey site parsers:")
    for site in key_sites:
        if site in url_parsers:
            pattern, prefix = url_parsers[site]
            print(f"  {site:12} -> {pattern.pattern}")
            if prefix:
                print(f"               Prefix: {prefix}")
