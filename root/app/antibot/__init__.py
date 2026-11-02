"""Anti-bot defense detection, challenge solving, and session impersonation."""

from fanficfare.fetchers.base_fetcher import LWPCookieJar

from antibot.anubis_client import (
    DEFAULT_USER_AGENT,
    clear_anubis_protected_sites,
    ensure_anubis_session,
    is_anubis_challenge,
    is_site_anubis_protected,
    mark_site_anubis_protected,
    probe_and_solve_anubis,
    solve_anubis_challenge,
)
from antibot.anubis_pow import (
    solve_pow,
    solve_sha256_pow,
    validate_anubis_hash,
)
from antibot.cookies import (
    clear_site_cookiejars,
    get_site_cookiejar,
    inspect_cookiejar_file,
    mask_cookie_value,
    resolve_cookiejar_path,
    set_site_cookiejar,
)
from antibot.flaresolverr import (
    FlareSolverrEndpointConfig,
    destroy_flaresolverr_session,
    get_flaresolverr_configs,
    is_flaresolverr_crash,
    list_flaresolverr_sessions,
    probe_flaresolverr_health,
    recover_flaresolverr_crashes,
)
from antibot.impersonation import (
    CURL_CFFI_AVAILABLE,
    ImpersonatedResponse,
    ImpersonatedSession,
    install_impersonated_session,
    is_impersonated_session_installed,
    uninstall_impersonated_session,
)

__all__ = [
    "DEFAULT_USER_AGENT",
    "mark_site_anubis_protected",
    "is_site_anubis_protected",
    "clear_anubis_protected_sites",
    "is_anubis_challenge",
    "solve_anubis_challenge",
    "probe_and_solve_anubis",
    "ensure_anubis_session",
    "validate_anubis_hash",
    "solve_pow",
    "solve_sha256_pow",
    "get_site_cookiejar",
    "set_site_cookiejar",
    "clear_site_cookiejars",
    "mask_cookie_value",
    "resolve_cookiejar_path",
    "inspect_cookiejar_file",
    "FlareSolverrEndpointConfig",
    "is_flaresolverr_crash",
    "get_flaresolverr_configs",
    "list_flaresolverr_sessions",
    "destroy_flaresolverr_session",
    "probe_flaresolverr_health",
    "recover_flaresolverr_crashes",
    "CURL_CFFI_AVAILABLE",
    "ImpersonatedResponse",
    "ImpersonatedSession",
    "install_impersonated_session",
    "uninstall_impersonated_session",
    "is_impersonated_session_installed",
    "LWPCookieJar",
]
