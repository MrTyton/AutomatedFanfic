"""
Per-site CookieJar session cache for worker pool threads.
"""

import threading

from utils import ff_logging

_site_cookiejars: dict[str, object] = {}
_last_personal_ini_content: str | None = None
_site_cookiejars_lock = threading.Lock()


def get_site_cookiejar(site: str, personal_ini_content: str) -> object | None:
    """Return the persisted FanFicFare cookiejar for a site, invalidating all jars if personal.ini changed."""
    global _last_personal_ini_content
    with _site_cookiejars_lock:
        if (
            _last_personal_ini_content is not None
            and _last_personal_ini_content != personal_ini_content
        ):
            _site_cookiejars.clear()
            ff_logging.log_debug(
                "\tpersonal.ini changed — cleared cached site cookiejars"
            )
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
