"""
FanFicFare execution engine and configuration bridge.
"""

import configparser
import copy
from dataclasses import dataclass, field
import functools
import importlib.metadata
import optparse
from pathlib import Path
import re
from typing import cast

lazy from fanficfare import adapters as fff_adapters
lazy from fanficfare import cli as fff_cli
from calibre_integration import calibre_info
from config.config_store import read_ini_file_cached
from models import fanfic_info
from parsers import regex_parsing
from utils import anubis_solver
from utils import ff_logging
from utils import thread_stdout
from utils import url_utils
from workers import cookie_cache
from workers import impersonated_session

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class FanFicFareResult:
    """Structured result from a FanFicFare direct API call."""

    failure_messages: list[str] = field(default_factory=list)
    forceable_messages: list[str] = field(default_factory=list)
    exception: BaseException | None = None
    target_url: str = ""
    effective_user_agent: str = ""
    captured_output: str = ""

    @property
    def has_failure(self) -> bool:
        return bool(self.failure_messages) or self.exception is not None

    @property
    def is_forceable(self) -> bool:
        return bool(self.forceable_messages)


# ---------------------------------------------------------------------------
# Configuration and URL helpers
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=64)
def extract_output_filename_template(ini_text: str, site: str | None = None) -> str:
    """Return the filename-only portion of the user's output_filename template.

    Mirrors FanFicFare's config priority: [overrides] > [site-domain] > [defaults].
    ``site`` is the fanfic.site value (e.g. ``archiveofourown``) used to find
    a matching ini section (e.g. ``[archiveofourown.org]``) so per-site filename
    customisations are respected.

    Any directory prefix in the template is stripped — we control the directory;
    the user controls the filename pattern.

    Falls back to a sensible default if the setting is absent or unparseable.
    """
    _DEFAULT = "${title}-${siteabbrev}_${storyId}.epub"
    if not ini_text:
        return _DEFAULT

    sections_to_check = ["overrides"]

    try:
        parser = configparser.RawConfigParser(strict=False)
        parser.read_string(ini_text)

        if site:
            site_lower = site.lower()
            for section in parser.sections():
                if (
                    section not in ("overrides", "defaults")
                    and site_lower in section.lower()
                ):
                    sections_to_check.append(section)
                    break

        sections_to_check.append("defaults")

        for section in sections_to_check:
            try:
                template = parser.get(section, "output_filename")
                return template.rsplit("/", 1)[-1]
            except configparser.NoSectionError, configparser.NoOptionError:
                continue
    except Exception:
        pass
    return _DEFAULT


def resolve_fanficfare_user_agent(
    target_url: str,
    passed_defaultsini: str | None,
    passed_personalini: str,
    options: optparse.Values,
) -> str:
    """Resolve the effective User-Agent for target_url according to FanFicFare configuration."""
    if not target_url:
        return anubis_solver.DEFAULT_USER_AGENT
    try:
        resolved_opts = copy.copy(options)
        conf = fff_cli.get_configuration(
            target_url,
            passed_defaultsini=passed_defaultsini,
            passed_personalini=passed_personalini,
            options=resolved_opts,
        )
        adapter = fff_adapters.getAdapter(conf, target_url)
        ua = adapter.getConfig("user_agent")
        if ua and ua.strip():
            return ua.strip()
    except Exception as e:
        ff_logging.log_debug(
            f"Could not resolve FFF user_agent for {target_url} ({e}); using default browser UA"
        )
    return anubis_solver.DEFAULT_USER_AGENT


def resolve_target_url(
    fanfic: fanfic_info.FanficInfo,
    path_or_url: str,
    captured_output: str,
) -> str:
    """Resolve the HTTP(S) URL for FanFicFare execution or probing."""
    raw_url = getattr(fanfic, "url", "")
    if raw_url and not raw_url.endswith(".epub"):
        return url_utils.normalize_url(raw_url)
    if captured_output:
        match = re.search(r"URL:\s*(https?://[^\s,]+)", captured_output)
        if match:
            return match.group(1).strip()
    if path_or_url and not path_or_url.endswith(".epub"):
        return url_utils.normalize_url(path_or_url)
    return ""


def run_fanficfare_download(
    path_or_url: str,
    options: optparse.Values,
    passed_defaultsini: str | None,
    passed_personalini: str,
    site_key: str,
) -> tuple[FanFicFareResult, str]:
    """Execute a single FanFicFare download attempt with stdout capture, error detection, and cookie persistence."""
    result = FanFicFareResult()

    def warn_callback(msg: str) -> None:
        msg_str = str(msg)
        ff_logging.log(f"\tFanFicFare warn: {msg_str}")
        if regex_parsing.check_failure_from_message(msg_str):
            result.failure_messages.append(msg_str)
        elif regex_parsing.check_forceable_from_message(msg_str):
            result.forceable_messages.append(msg_str)

    def fail_callback(msg: str) -> None:
        msg_str = str(msg)
        ff_logging.log_failure(f"\tFanFicFare fail: {msg_str}")
        result.failure_messages.append(msg_str)

    tl_stdout = thread_stdout.ensure_tl_stdout()
    impersonated_session.install_impersonated_session()
    captured_output = ""
    try:
        with tl_stdout.capture() as captured_buf:
            try:
                fff_cli.do_download(
                    path_or_url,
                    options,
                    passed_defaultsini=passed_defaultsini,
                    passed_personalini=passed_personalini,
                    warn=warn_callback,
                    fail=fail_callback,
                )
            finally:
                captured_output = captured_buf.getvalue()
    except Exception as e:
        result.exception = e
        ff_logging.log_failure(f"\tFanFicFare raised exception: {e}")
    finally:
        updated_cookiejar = vars(options).get("cookiejar")
        if updated_cookiejar is not None and site_key:
            cookie_cache.set_site_cookiejar(site_key, updated_cookiejar)

    if captured_output:
        ff_logging.log_debug(f"\tFanFicFare stdout: {captured_output}")

    if regex_parsing.check_failure_from_message(captured_output):
        result.failure_messages.append(
            f"FanFicFare silent failure: {captured_output.strip()}"
        )

    return result, captured_output


# ---------------------------------------------------------------------------
# Public API: direct Python API execution
# ---------------------------------------------------------------------------


def execute_fanficfare_direct(
    cdb: calibre_info.CalibreInfo,
    fanfic: fanfic_info.FanficInfo,
    path_or_url: str,
    temp_dir: str,
) -> FanFicFareResult:
    """
    Execute a FanFicFare download/update directly via the Python API.

    Replaces the subprocess-based execute_command() approach for lower
    per-download overhead. Uses fanficfare.cli.do_download() with custom
    warn/fail callbacks to intercept structured error conditions, and a
    thread-local stdout proxy to catch print()-based messages
    (equal_chapters, failed_login).

    Args:
        cdb: Calibre configuration (update_method, ini file paths, etc.).
        fanfic: Fanfiction task being processed.
        path_or_url: Epub file path for updates, or story URL for new downloads.
        temp_dir: Temporary working directory; epub output is directed here.

    Returns:
        FanFicFareResult containing classified failure, forceable messages,
        target_url, effective_user_agent, and captured stdout.
    """
    passed_defaultsini: str | None = None
    if not cdb.default_ini:
        ff_logging.log_debug("\tdefaults.ini: path not configured")
    elif not Path(cdb.default_ini).is_file():
        ff_logging.log(
            f"\tdefaults.ini: path configured ({cdb.default_ini}) but file does not exist",
            "WARNING",
        )
    else:
        try:
            passed_defaultsini = read_ini_file_cached(Path(cdb.default_ini))
            if passed_defaultsini is None:
                passed_defaultsini = Path(cdb.default_ini).read_text(encoding="utf-8")
            ff_logging.log_debug(
                f"\tdefaults.ini: loaded {len(passed_defaultsini)} bytes from {cdb.default_ini}"
            )
        except Exception as e:
            ff_logging.log(
                f"Could not read defaults.ini ({cdb.default_ini}): {e}", "WARNING"
            )

    if passed_defaultsini is None:
        try:
            defaults_path = Path(fff_cli.__file__).parent / "defaults.ini"
            if defaults_path.is_file():
                passed_defaultsini = defaults_path.read_text(encoding="utf-8")
        except Exception:
            pass

    personal_ini_base = ""
    if not cdb.personal_ini:
        ff_logging.log_debug(
            "\tpersonal.ini: path not configured — running with FanFicFare defaults"
        )
    elif not Path(cdb.personal_ini).is_file():
        ff_logging.log(
            f"\tpersonal.ini: path configured ({cdb.personal_ini}) but file does not exist",
            "WARNING",
        )
    else:
        try:
            cached_personal = read_ini_file_cached(Path(cdb.personal_ini))
            personal_ini_base = (
                cached_personal
                if cached_personal is not None
                else Path(cdb.personal_ini).read_text(encoding="utf-8")
            )
            ff_logging.log_debug(
                f"\tpersonal.ini: loaded {len(personal_ini_base)} bytes from {cdb.personal_ini}"
            )
        except Exception as e:
            ff_logging.log(
                f"Could not read personal.ini ({cdb.personal_ini}): {e}", "WARNING"
            )

    output_dir = Path(temp_dir).as_posix()
    _filename_template = extract_output_filename_template(
        personal_ini_base, fanfic.site
    )
    output_override = (
        f"\n[overrides]\noutput_filename: {output_dir}/{_filename_template}\n"
    )

    default_ua_fallback = (
        f"[defaults]\nuser_agent: {anubis_solver.DEFAULT_USER_AGENT}\n\n"
    )
    passed_personalini = default_ua_fallback + personal_ini_base + output_override

    # Parse argv-equivalent flags through FanFicFare's own option parser so
    # all defaults and validation logic are applied correctly.
    argv = build_argv(cdb, fanfic)
    parser = fff_cli.mkParser(calibre=False)
    options, _ = parser.parse_args(argv)
    fff_cli.expandOptions(options)

    site_key = getattr(fanfic, "site", "") or ""
    cached_cookiejar = cookie_cache.get_site_cookiejar(site_key, personal_ini_base)
    target_url = resolve_target_url(fanfic, path_or_url, "")

    effective_user_agent = resolve_fanficfare_user_agent(
        target_url,
        passed_defaultsini,
        passed_personalini,
        options,
    )

    if anubis_solver.is_site_anubis_protected(site_key):
        cookiejar = anubis_solver.ensure_anubis_session(
            site=site_key,
            url=target_url,
            user_agent=effective_user_agent,
            cookiejar=cast(anubis_solver.LWPCookieJar | None, cached_cookiejar),
        )
        options.cookiejar = cookiejar
        cookie_cache.set_site_cookiejar(site_key, cookiejar)
    elif cached_cookiejar is not None:
        options.cookiejar = cached_cookiejar

    ff_logging.log(f"Executing FanFicFare directly: {path_or_url}")

    result, captured_output = run_fanficfare_download(
        path_or_url,
        options,
        passed_defaultsini,
        passed_personalini,
        site_key,
    )

    # Attach contextual metadata for caller / pipeline inspection
    result.captured_output = captured_output
    if not target_url and captured_output:
        target_url = resolve_target_url(fanfic, path_or_url, captured_output)
    result.target_url = target_url
    result.effective_user_agent = (
        effective_user_agent
        if effective_user_agent != anubis_solver.DEFAULT_USER_AGENT or not target_url
        else resolve_fanficfare_user_agent(
            target_url,
            passed_defaultsini,
            passed_personalini,
            options,
        )
    )

    return result


def build_argv(
    cdb: calibre_info.CalibreInfo,
    fanfic: fanfic_info.FanficInfo,
) -> list[str]:
    """
    Build the FanFicFare options argv equivalent to construct_fanficfare_command().

    Does NOT include the target URL/path — that is passed separately to
    do_download() as its first positional argument.
    """
    update_method = cdb.update_method
    is_force_behavior = (
        fanfic.behavior == "force" and update_method != "update_no_force"
    )

    argv: list[str] = []

    if update_method == "update_always" and not is_force_behavior:
        argv.append("-U")
    elif update_method in ("force", "force_override") or is_force_behavior:
        argv.extend(["-u", "--force"])
    else:
        argv.append("-u")

    argv.extend(["--update-cover", "--non-interactive"])

    if ff_logging.is_verbose():
        argv.append("--debug")

    return argv


def get_fanficfare_version() -> str:
    """Return the installed FanFicFare version via importlib.metadata."""
    try:
        return importlib.metadata.version("fanficfare")
    except Exception as e:
        ff_logging.log(f"Failed to get FanFicFare version: {e}", "WARNING")
        return f"Error: {e}"
