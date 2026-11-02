"""Per-site CookieJar session caching and cookiejar inspection utilities."""

import configparser
from http.cookiejar import LWPCookieJar, MozillaCookieJar
from pathlib import Path
import threading
from typing import Any

from config.ini_resolver import resolve_ini_path
import ff_logging

_site_cookiejars: dict[str, object] = {}
_last_personal_ini_content: str | None = None
_site_cookiejars_lock = threading.Lock()


def get_site_cookiejar(
    site: str, personal_ini_content: str | None = None
) -> object | None:
    """Return the persisted FanFicFare cookiejar for a site, invalidating all jars if personal.ini changed."""
    global _last_personal_ini_content
    with _site_cookiejars_lock:
        if (
            personal_ini_content is not None
            and _last_personal_ini_content is not None
            and _last_personal_ini_content != personal_ini_content
        ):
            _site_cookiejars.clear()
            ff_logging.log_debug(
                "\tpersonal.ini changed — cleared cached site cookiejars"
            )
        if personal_ini_content is not None:
            _last_personal_ini_content = personal_ini_content
        if not site:
            return None
        return _site_cookiejars.get(site)


def set_site_cookiejar(site: str, cookiejar: object) -> None:
    """Store the FanFicFare cookiejar for a site so sessions persist across tasks."""
    if not site:
        return
    with _site_cookiejars_lock:
        _site_cookiejars[site] = cookiejar


def clear_site_cookiejars() -> None:
    """Clear all cached per-site cookiejars and reset personal.ini tracking."""
    global _last_personal_ini_content
    with _site_cookiejars_lock:
        _site_cookiejars.clear()
        _last_personal_ini_content = None


def mask_cookie_value(val: str | None) -> str:
    """Mask secret cookie value while preserving length cue."""
    if not val:
        return ""
    if len(val) > 8:
        return f"{val[:3]}...{val[-3:]}"
    return "********"


def resolve_cookiejar_path(state: Any, domain: str) -> Path | None:
    """Locate configured or disk cookiejar for a domain."""
    raw_personal = None
    if getattr(state, "config", None) and getattr(state.config, "calibre", None):
        raw_personal = state.config.calibre.personal_ini
    elif getattr(state, "config_store", None):
        raw_personal = state.config_store.get_resolved_personal_ini()

    personal_path = (
        resolve_ini_path(raw_personal, "personal.ini") if raw_personal else ""
    )
    if personal_path and Path(personal_path).is_file():
        try:
            parser = configparser.RawConfigParser(strict=False)
            parser.read(personal_path, encoding="utf-8")
            sections = [s for s in parser.sections() if domain.lower() in s.lower()]
            sections.append("defaults")
            for sec in sections:
                if parser.has_option(sec, "cookiejar"):
                    cj = parser.get(sec, "cookiejar").strip()
                    if cj:
                        candidate = Path(cj)
                        if not candidate.is_absolute():
                            candidate = Path(personal_path).parent / candidate
                        return candidate
        except Exception:
            pass

    for candidate in [
        Path(f"{domain}.cookies.txt"),
        Path(f"cookies/{domain}.txt"),
        Path(f"{domain}.txt"),
    ]:
        if candidate.is_file():
            return candidate

    return None


def inspect_cookiejar_file(state: Any, domain: str) -> dict[str, object]:
    """Inspect cookies for domain without leaking secret tokens."""
    norm_domain = domain.strip().lower()
    jar_path = resolve_cookiejar_path(state, norm_domain)

    if jar_path is None or not jar_path.is_file():
        return {
            "domain": domain,
            "cookie_count": 0,
            "cookies": [],
            "file_path": None,
            "message": "No cookiejar found",
        }

    jar = LWPCookieJar(str(jar_path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        try:
            m_jar = MozillaCookieJar(str(jar_path))
            m_jar.load(ignore_discard=True, ignore_expires=True)
            jar = m_jar
        except Exception as exc:
            return {
                "domain": domain,
                "cookie_count": 0,
                "cookies": [],
                "file_path": str(jar_path),
                "message": f"Failed to parse cookiejar: {exc}",
            }

    cookies_list: list[dict[str, object]] = []
    for c in jar:
        cookies_list.append(
            {
                "name": c.name,
                "domain": c.domain,
                "path": c.path,
                "expires": c.expires,
                "secure": c.secure,
                "discard": c.discard,
                "value": mask_cookie_value(c.value),
            }
        )

    return {
        "domain": domain,
        "cookie_count": len(cookies_list),
        "cookies": cookies_list,
        "file_path": str(jar_path),
        "message": "Cookiejar loaded successfully",
    }
