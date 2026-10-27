"""
Backwards-compatible facade for FanFicFare runner and session cookie caching.
"""

from utils import ff_logging
from utils.thread_stdout import ThreadLocalStdout, ensure_tl_stdout
from workers.cookie_cache import (
    clear_site_cookiejars,
    get_site_cookiejar,
    set_site_cookiejar,
)
from workers.fff_runner import (
    FanFicFareResult,
    build_argv,
    execute_fanficfare_direct,
    extract_output_filename_template,
    get_fanficfare_version,
    resolve_fanficfare_user_agent,
    resolve_target_url,
    run_fanficfare_download,
)

# Private aliases for backwards compatibility with existing unit tests and callers
_ThreadLocalStdout = ThreadLocalStdout
_ensure_tl_stdout = ensure_tl_stdout
_get_site_cookiejar = get_site_cookiejar
_set_site_cookiejar = set_site_cookiejar
_build_argv = build_argv
_extract_output_filename_template = extract_output_filename_template
_resolve_fanficfare_user_agent = resolve_fanficfare_user_agent
_resolve_target_url = resolve_target_url
_run_fanficfare_download = run_fanficfare_download

__all__ = [
    "FanFicFareResult",
    "ThreadLocalStdout",
    "_ThreadLocalStdout",
    "_build_argv",
    "_ensure_tl_stdout",
    "_extract_output_filename_template",
    "_get_site_cookiejar",
    "_resolve_fanficfare_user_agent",
    "_resolve_target_url",
    "_run_fanficfare_download",
    "_set_site_cookiejar",
    "build_argv",
    "clear_site_cookiejars",
    "ensure_tl_stdout",
    "execute_fanficfare_direct",
    "extract_output_filename_template",
    "ff_logging",
    "get_fanficfare_version",
    "get_site_cookiejar",
    "resolve_fanficfare_user_agent",
    "resolve_target_url",
    "run_fanficfare_download",
    "set_site_cookiejar",
]
