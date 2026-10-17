"""
Command execution logic for FanFicFare integration.
"""

import configparser
import functools
import io
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
import importlib.metadata
from pathlib import Path
from typing import Any

lazy from fanficfare import cli as fff_cli
from config.config_store import read_ini_file_cached
from utils import ff_logging
from calibre_integration import calibre_info
from models import fanfic_info
from parsers import regex_parsing

# ---------------------------------------------------------------------------
# Thread-local stdout proxy
# ---------------------------------------------------------------------------
#
# FanFicFare emits certain status messages via plain print() rather than its
# warn/fail callbacks:
#   - "already contains N chapters"  (equal_chapters — permanent failure)
#   - "Login Failed on non-interactive process."  (failed_login — permanent failure)
#
# This proxy replaces sys.stdout once at first use and routes each thread's
# print() output into a per-thread StringIO when a capture() context is active,
# falling through to the real stdout otherwise.


class _ThreadLocalStdout:
    """Thread-safe sys.stdout proxy with per-thread capture capability."""

    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped
        self._local = threading.local()

    def write(self, s: str) -> int:
        buf = getattr(self._local, "capture_buffer", None)
        if buf is not None:
            return buf.write(s)
        return self._wrapped.write(s)

    def flush(self) -> None:
        buf = getattr(self._local, "capture_buffer", None)
        if buf is not None:
            buf.flush()
        else:
            self._wrapped.flush()

    def fileno(self) -> int:
        try:
            return self._wrapped.fileno()
        except AttributeError, io.UnsupportedOperation:
            raise io.UnsupportedOperation("fileno")

    @property
    def encoding(self) -> str:
        return getattr(self._wrapped, "encoding", "utf-8")

    @property
    def errors(self) -> str:
        return getattr(self._wrapped, "errors", "strict")

    @contextmanager
    def capture(self):
        """Capture this thread's stdout into a StringIO for the duration of the block."""
        self._local.capture_buffer = io.StringIO()
        try:
            yield self._local.capture_buffer
        finally:
            self._local.capture_buffer = None


_tl_stdout: _ThreadLocalStdout | None = None
_tl_stdout_lock = threading.Lock()


def _ensure_tl_stdout() -> _ThreadLocalStdout:
    """Install the thread-local stdout proxy the first time it is needed."""
    global _tl_stdout
    if _tl_stdout is None:
        with _tl_stdout_lock:
            if _tl_stdout is None:
                _tl_stdout = _ThreadLocalStdout(sys.stdout)
                sys.stdout = _tl_stdout
    return _tl_stdout


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class FanFicFareResult:
    """Structured result from a FanFicFare direct API call."""

    failure_messages: list[str] = field(default_factory=list)
    forceable_messages: list[str] = field(default_factory=list)
    exception: BaseException | None = None

    @property
    def has_failure(self) -> bool:
        return bool(self.failure_messages) or self.exception is not None

    @property
    def is_forceable(self) -> bool:
        return bool(self.forceable_messages)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=64)
def _extract_output_filename_template(ini_text: str, site: str | None = None) -> str:
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

        # Find the site-specific section by substring match:
        # fanfic.site="archiveofourown" matches "[archiveofourown.org]"
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
                # Strip any directory component the user may have set —
                # we control the directory; they control the filename pattern.
                return template.rsplit("/", 1)[-1]
            except configparser.NoSectionError, configparser.NoOptionError:
                continue
    except Exception:
        pass
    return _DEFAULT


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
        FanFicFareResult containing classified failure and forceable messages.
    """
    result = FanFicFareResult()

    # warn() carries: bad_chapters, chapter_difference, more_chapters,
    # no_url (wrapped in "Failed to read epub for update…").
    # fail() carries: AccessDenied, StoryDoesNotExist, UnknownSite, etc.

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

    # Pass the app's ini files as strings so they override any system-level
    # fanficfare settings.
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

    # Build personal ini: user's personal.ini + output_filename override.
    # The direct Python API has no cwd concept (unlike the old subprocess approach
    # which used cwd=temp_dir).  We inject output_filename via [overrides] —
    # FanFicFare's highest-priority ini section — so the file always lands in
    # temp_dir regardless of any path the user may have set.
    #
    # We respect the user's filename *template* (e.g. their custom naming
    # convention) but strip any directory component: we control the directory,
    # they control the filename pattern.
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
    _filename_template = _extract_output_filename_template(
        personal_ini_base, fanfic.site
    )
    output_override = (
        "\n[overrides]\n" f"output_filename: {output_dir}/{_filename_template}\n"
    )

    passed_personalini = personal_ini_base + output_override

    # Parse argv-equivalent flags through FanFicFare's own option parser so
    # all defaults and validation logic are applied correctly.
    argv = _build_argv(cdb, fanfic)
    parser = fff_cli.mkParser(calibre=False)
    options, _ = parser.parse_args(argv)
    fff_cli.expandOptions(options)

    ff_logging.log(f"Executing FanFicFare directly: {path_or_url}")

    tl_stdout = _ensure_tl_stdout()

    try:
        with tl_stdout.capture() as captured_buf:
            fff_cli.do_download(
                path_or_url,
                options,
                passed_defaultsini=passed_defaultsini,
                passed_personalini=passed_personalini,
                warn=warn_callback,
                fail=fail_callback,
            )
        captured_output = captured_buf.getvalue()
    except Exception as e:
        result.exception = e
        ff_logging.log_failure(f"\tFanFicFare raised exception: {e}")
        return result

    if captured_output:
        ff_logging.log_debug(f"\tFanFicFare stdout: {captured_output}")

    # Detect print()-based failure conditions not surfaced via callbacks:
    #   equal_chapters  → "already contains N chapters"
    #   failed_login    → "Login Failed on non-interactive process."
    if regex_parsing.check_failure_from_message(captured_output):
        result.failure_messages.append(
            f"FanFicFare silent failure: {captured_output.strip()}"
        )

    return result


def _build_argv(
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
