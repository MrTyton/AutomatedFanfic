"""
Auto-generated URL parsers from FanFicFare adapters.

This module automatically generates regex patterns for URL parsing by extracting
the site examples from FanFicFare adapters, eliminating the need for manual
maintenance of URL patterns.
"""

import re
import fanficfare.adapters as adapters
from urllib.parse import urlparse
from typing import Dict, Tuple


def generate_url_parsers_from_fanficfare() -> Dict[str, Tuple[re.Pattern, str]]:
    """
    Generate url_parsers dictionary from FanFicFare adapters automatically.
    
    Returns:
        Dict[str, Tuple[re.Pattern, str]]: Dictionary mapping site identifiers
        to tuples of (compiled regex pattern, URL prefix)
    """
    examples = adapters.getSiteExamples()
    url_parsers = {}
    
    for site, urls in examples:
        if not urls:
            continue
            
        # Use the first URL as the pattern base
        first_url = urls[0]
        parsed = urlparse(first_url)
        domain = parsed.netloc
        path = parsed.path
        query = parsed.query
        
        # Create site identifier
        site_id = _generate_site_identifier(domain, site)
        
        # Generate pattern and prefix using algorithmic rules
        pattern, prefix = _generate_pattern_and_prefix(domain, path, query)
        
        try:
            compiled_pattern = re.compile(pattern)
            url_parsers[site_id] = (compiled_pattern, prefix)
        except re.error as e:
            print(f"Warning: Failed to compile regex for {site}: {e}")
            continue
    
    # Add fallback pattern for any unrecognized URLs
    url_parsers["other"] = (re.compile(r"https?://(.*)"), "")
    
    return url_parsers


def _generate_pattern_and_prefix(domain: str, path: str, query: str) -> Tuple[str, str]:
    """
    Generate regex pattern and prefix using algorithmic rules.
    
    Args:
        domain: The domain name (e.g., 'www.fanfiction.net')
        path: The URL path (e.g., '/s/12345/1/')
        query: The query string (e.g., 'chapter=1')
        
    Returns:
        Tuple of (regex_pattern, url_prefix)
    """
    
    # Determine URL structure rules
    is_forum_site = 'forum' in domain or 'threads' in path
    has_www = domain.startswith('www.')
    is_fanfiction_net = 'fanfiction.net' in domain
    
    # Clean domain for pattern matching
    clean_domain = domain[4:] if has_www else domain  # Remove www. if present
    
    # Build the core path pattern - simple approach
    if is_forum_site:
        # For forums: match threads up to the thread ID
        if '/threads/' in path:
            path_pattern = r'/threads/[^/]*\.\d+'
        else:
            path_pattern = re.escape(path)
            path_pattern = re.sub(r'\\d+', r'\\d+', path_pattern)
    else:
        # For story sites: match the core story pattern
        if '/s/' in path:  # FFN/FictionPress style
            path_pattern = r'/s/\d+'
        elif '/works/' in path:  # AO3 style
            path_pattern = r'/works/\d+'
        elif '/fiction/' in path:  # RoyalRoad style
            path_pattern = r'/fiction/\d+'
        else:
            # Generic: escape and replace numbers
            path_pattern = re.escape(path)
            path_pattern = re.sub(r'\\d+', r'\\d+', path_pattern)
    
    # Build query pattern if needed
    query_part = ""
    if query:
        query_escaped = re.escape(query)
        query_pattern = re.sub(r'\\d+', r'\\d+', query_escaped)
        query_part = f"\\?{query_pattern}"
    
    # Apply site-specific rules for capture groups and prefixes
    if is_fanfiction_net:
        # Special case: fanfiction.net always gets www. prefix and captures path only
        # Create two patterns: one for URLs with chapters (trailing slash) and one without
        domain_pattern = f"(?:www\\.)?{re.escape(clean_domain)}"
        
        # Pattern that captures /s/ID/ for URLs with chapter info
        pattern_with_chapter = f"https?://{domain_pattern}(/s/\\d+)/\\d+.*"
        # Pattern that captures /s/ID for URLs without chapter info  
        pattern_without_chapter = f"https?://{domain_pattern}(/s/\\d+)/?$"
        
        # Combine both patterns
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
        # Sites without www: capture full domain + path
        domain_pattern = re.escape(domain)
        pattern = f"https?://({domain_pattern}{path_pattern}{query_part})/?.*"
        prefix = ""
    
    return pattern, prefix


def _build_path_pattern(path: str, is_forum_site: bool) -> str:
    """Build a regex pattern for the URL path."""
    # This function is now simplified and integrated into _generate_pattern_and_prefix
    return path


def _get_essential_forum_path(path_pattern: str) -> str:
    """Extract the essential part of a forum URL path (up to thread ID)."""
    # This function is now simplified and integrated into _generate_pattern_and_prefix
    return path_pattern


def _generate_site_identifier(domain: str, site: str) -> str:
    """Generate a meaningful site identifier from the domain algorithmically."""
    
    # Use algorithmic approach only - no special cases
    parts = domain.split('.')
    if len(parts) >= 2:
        # Skip common prefixes
        if parts[0] in ['www', 'forums', 'archive', 'forum']:
            return parts[1] if len(parts) > 2 else parts[0]
        else:
            return parts[0]
    
    return site.lower().replace('.', '_').replace('-', '_')


# Generate the URL parsers when this module is imported
url_parsers = generate_url_parsers_from_fanficfare()

# Print some statistics
if __name__ == "__main__":
    print(f"Auto-generated {len(url_parsers)} URL parsers from FanFicFare adapters")
    
    # Show some key parsers
    key_sites = ['ffnet', 'ao3', 'sb', 'sv', 'qq', 'royalroad']
    print("\nKey site parsers:")
    for site in key_sites:
        if site in url_parsers:
            pattern, prefix = url_parsers[site]
            print(f"  {site:12} -> {pattern.pattern}")
            if prefix:
                print(f"               Prefix: {prefix}")
else:
    print(f"Loaded {len(url_parsers)} auto-generated URL parsers from FanFicFare")
