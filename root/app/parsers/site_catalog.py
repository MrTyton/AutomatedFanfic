"""Fanfiction site catalog and adapter metadata discovery."""

import functools
import re
from urllib.parse import urlparse

lazy import fanficfare.adapters as adapters
from parsers.url_patterns import _generate_site_identifier


def clean_display_name_from_adapter(attr: str) -> str:
    """Algorithmically derives a clean display name from a FanFicFare adapter class name."""
    clean = re.sub(r"(Site)?Adapter$", "", attr)
    clean = re.sub(r"^(WWW|Forums?|Base)", "", clean)
    clean = re.sub(r"(Com|Org|Net|De|Fr|CoUk|Tv|Me|Live)$", "", clean)
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+", clean)
    return " ".join(words) if words else clean


def clean_display_name_from_domain(domain: str) -> str:
    """Algorithmically formats a domain or site identifier into a human-readable display name."""
    clean = re.sub(r"^(www|forums?|forum|archive)\.", "", domain, flags=re.IGNORECASE)
    clean = re.sub(
        r"\.(com|org|net|de|fr|co\.uk|me|live|tv|info|io)$",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    parts = re.split(r"[-_.]", clean)
    return " ".join(p.capitalize() for p in parts if p)


@functools.lru_cache(maxsize=1)
def get_supported_sites_catalog() -> dict[str, dict[str, str]]:
    """Algorithmically extracts all supported sites, their primary domains, and display names from FanFicFare adapters.

    Returns:
        Mapping of site_id -> {"site": site_id, "domain": domain, "display_name": display_name}
    """
    catalog: dict[str, dict[str, str]] = {}
    try:
        for name in dir(adapters):
            if not name.startswith("adapter_"):
                continue
            mod = getattr(adapters, name)
            for attr in dir(mod):
                if attr.endswith("Adapter") and not attr.startswith("Base"):
                    cls = getattr(mod, attr)
                    domain = getattr(cls, "getSiteDomain", lambda: "")()
                    if not domain:
                        continue
                    site_id = _generate_site_identifier(domain, domain)
                    display_name = clean_display_name_from_adapter(attr)
                    catalog[site_id] = {
                        "site": site_id,
                        "domain": domain,
                        "display_name": display_name,
                    }

        for site, urls in adapters.getSiteExamples():
            if not urls:
                continue
            parsed = urlparse(urls[0])
            domain = parsed.netloc
            site_id = _generate_site_identifier(domain, site)
            if site_id not in catalog:
                catalog[site_id] = {
                    "site": site_id,
                    "domain": domain,
                    "display_name": clean_display_name_from_domain(domain),
                }
    except Exception:
        pass
    return catalog
