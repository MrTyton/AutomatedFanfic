"""
Command execution logic for FanFicFare integration.
"""

import io
import sys
import shlex
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

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

    def __init__(self, wrapped: object) -> None:
        self._wrapped = wrapped
        self._local = threading.local()

    def write(self, s: str) -> int:
        buf = getattr(self._local, "capture_buffer", None)
        if buf is not None:
            return buf.write(s)
        return self._wrapped.write(s)  # type: ignore[attr-defined]

    def flush(self) -> None:
        buf = getattr(self._local, "capture_buffer", None)
        if buf is not None:
            buf.flush()
        else:
            self._wrapped.flush()  # type: ignore[attr-defined]

    def fileno(self) -> int:
        try:
            return self._wrapped.fileno()  # type: ignore[attr-defined]
        except (AttributeError, io.UnsupportedOperation):
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
    from fanficfare.cli import do_download, expandOptions, mkParser

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
    if cdb.default_ini and Path(cdb.default_ini).is_file():
        try:
            passed_defaultsini = Path(cdb.default_ini).read_text(encoding="utf-8")
        except Exception as e:
            ff_logging.log(
                f"Could not read defaults.ini ({cdb.default_ini}): {e}", "WARNING"
            )

    # Build personal ini: user's personal.ini + output_filename override.
    # The override routes new epub output to temp_dir, avoiding os.chdir()
    # (which is process-global and therefore not thread-safe).
    output_dir = Path(temp_dir).as_posix()
    output_override = (
        "\n[defaults]\n"
        f"output_filename: {output_dir}/${{title}}-${{siteabbrev}}_${{storyId}}.epub\n"
    )

    personal_ini_base = ""
    if cdb.personal_ini and Path(cdb.personal_ini).is_file():
        try:
            personal_ini_base = Path(cdb.personal_ini).read_text(encoding="utf-8")
        except Exception as e:
            ff_logging.log(
                f"Could not read personal.ini ({cdb.personal_ini}): {e}", "WARNING"
            )

    passed_personalini = personal_ini_base + output_override

    # Parse argv-equivalent flags through FanFicFare's own option parser so
    # all defaults and validation logic are applied correctly.
    argv = _build_argv(cdb, fanfic)
    parser = mkParser()
    options, _ = parser.parse_args(argv)
    expandOptions(options)

    ff_logging.log(f"Executing FanFicFare directly: {path_or_url}")

    tl_stdout = _ensure_tl_stdout()

    try:
        with tl_stdout.capture() as captured_buf:
            do_download(
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
            "FanFicFare reported a silent failure condition (see stdout above)."
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
    """Get the FanFicFare version by running python -m fanficfare.cli --version.

    Returns:
        str: FanFicFare version string or error message if unavailable.
    """
    try:
        # Use simple list args for safer execution
        cmd = [sys.executable, "-m", "fanficfare.cli", "--version"]
        version_output = execute_command(cmd)

        # Try to find version number pattern
        import re

        match = re.search(r"(\d+\.\d+\.\d+)", version_output)
        if match:
            return match.group(1)

        return version_output.strip()
    except Exception as e:
        ff_logging.log(f"Failed to get FanFicFare version: {e}", "WARNING")
        return f"Error: {e}"


def execute_command(command: list[str] | str, cwd: str | None = None) -> str:
    """
    Executes a shell command and returns its output.

    Args:
        command (list[str] | str): The command to execute. Should be a list of arguments.
        cwd (str, optional): The directory to execute the command in.

    Returns:
        str: The output of the command.

    Raises:
        subprocess.CalledProcessError: If the command fails.
    """
    debug_msg = f"Executing command: {command}"

    if isinstance(command, str):
        # Basic splitting, not robust for quoted args
        cmd_list = shlex.split(command)
    else:
        cmd_list = command

    if cwd:
        debug_msg += f" (in {cwd})"

    # Always log the full command so operators can reproduce issues
    if isinstance(cmd_list, list):
        formatted_cmd = shlex.join(cmd_list)
        ff_logging.log(f"Executing: {formatted_cmd}")
        if cwd:
            ff_logging.log(f"\tWorking Directory: {cwd}")
    else:
        ff_logging.log(debug_msg)

    # Use subprocess.run for safer and more robust execution
    # shell=False is safer and less error-prone with list args
    # capture_output=True captures stdout/stderr
    # text=True decodes output to string
    result = subprocess.run(
        cmd_list,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,  # Raises CalledProcessError on non-zero exit code
    )

    # helper for compatibility with old check_output return style (just stdout usually)
    # merged stdout/stderr was common with check_output(stderr=STDOUT)
    # here we join them if both exist, or just return stdout
    output = result.stdout
    if result.stderr:
        output += "\nSTDERR:\n" + result.stderr

    return output


def construct_fanficfare_command(
    cdb: calibre_info.CalibreInfo,
    fanfic: fanfic_info.FanficInfo,
    path_or_url: str,
) -> list[str]:
    """
    Construct the appropriate FanFicFare CLI command based on configuration and fanfic state.

    This function builds the FanFicFare command list dynamically based on the
    Calibre configuration's update method and the fanfiction's requested behavior.

    Args:
        cdb (calibre_info.CalibreInfo): Calibre configuration containing the update_method
                                       setting that controls how updates are performed.
        fanfic (fanfic_info.FanficInfo): Fanfiction info object which may contain
                                        request-specific behavior overrides (like "force").
        path_or_url (str): The target URL or filesystem path to update/download.

    Returns:
        list[str]: Complete FanFicFare command arguments ready for execution.
    """
    update_method = cdb.update_method

    # Base command structure
    # We use sys.executable to ensure we use the same python interpreter
    command = [sys.executable, "-m", "fanficfare.cli"]

    # Check if fanfiction specifically requests force behavior
    # But ONLY if the global update method isn't set to 'update_no_force'
    # 'update_no_force' overrides individual force requests to prevent
    # accidental overwrites in restricted modes
    is_force_behavior = (
        fanfic.behavior == "force" and update_method != "update_no_force"
    )

    # Determine flags based on update_method and behavior
    if update_method == "update_always" and not is_force_behavior:
        # Update existing ebook if it exists (-U in CLI)
        command.append("-U")
    elif (
        update_method == "force"
        or update_method == "force_override"
        or is_force_behavior
    ):
        # Force update and overwrite (-u --force)
        # This is destructive and ignores 'new chapters only' checks
        command.extend(["-u", "--force"])
    else:
        # Default behavior: Normal update check (-u)
        # This covers 'normal_update' and 'update_no_force' cases
        # Also serves as fallback for unknown update methods
        command.append("-u")

    # Add standard flags
    # --update-cover: Always try to update the cover image
    # --non-interactive: Prevent CLI from asking questions (stalling process)
    command.extend(["--update-cover", "--non-interactive"])

    # Add debug flag if verbose logging is enabled in the application
    if ff_logging.is_verbose():
        command.append("--debug")

    # Add the target path or URL as the final argument
    command.append(path_or_url)

    return command
