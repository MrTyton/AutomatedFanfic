"""Custom logging module for AutomatedFanfic application.

This module provides colored console logging functionality with multiprocessing support
for the AutomatedFanfic application. It includes terminal color code definitions,
timestamp formatting, and both standard and debug logging capabilities with shared
state management across processes.

Key Features:
    - ANSI color code support for different log levels
    - Thread-safe verbose logging control via multiprocessing.Value
    - Timestamp formatting for all log messages
    - Specialized logging functions for failures and debug output
    - Multiprocessing-compatible shared state management
    - In-memory log ring buffer for web UI access

Classes:
    bcolors: Terminal color code constants for different logging levels

Functions:
    set_verbose: Controls debug logging output globally
    log: Core logging function with color and timestamp support
    log_failure: Convenience function for error message logging
    log_debug: Conditional debug logging based on verbose flag

Example:
    >>> import ff_logging
    >>> ff_logging.set_verbose(True)
    >>> ff_logging.log("Application started")
    >>> ff_logging.log_failure("Connection failed")
    >>> ff_logging.log_debug("Debug information")
"""

from __future__ import annotations

import collections
import datetime
from queue import Empty
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.queue_types import LogQueue

# Thread-local storage for worker-specific logging context
_thread_local = threading.local()

# ── In-memory log ring buffer ───────────────────────────────────
# Stores the most recent log entries for the web UI log viewer.
# Each entry is a dict with keys: timestamp, level, message.
_LOG_BUFFER_MAX = 2000
_log_buffer: collections.deque = collections.deque(maxlen=_LOG_BUFFER_MAX)
_log_buffer_lock = threading.Lock()

_STARTUP_LOG_BUFFER_MAX = 2000
_startup_log_buffer: collections.deque = collections.deque(
    maxlen=_STARTUP_LOG_BUFFER_MAX
)
_startup_capture_enabled = True
_STARTUP_COMPLETE_MARKERS = (
    "All processes started successfully",
    "Processes running. Press Ctrl+C to stop gracefully.",
)

# ── Cross-process log forwarding ────────────────────────────────
# When set, log() also puts entries into this queue so the web
# server process (which runs in a separate subprocess) can drain
# it and show logs from ALL processes, not just its own.
_log_forward_queue: LogQueue | None = None


def _append_log_entry(entry: dict) -> None:
    """Append an entry to runtime/startup buffers in a single critical section."""
    global _startup_capture_enabled
    message = str(entry.get("message", ""))

    with _log_buffer_lock:
        _log_buffer.append(entry)
        if _startup_capture_enabled:
            _startup_log_buffer.append(entry)
            if any(marker in message for marker in _STARTUP_COMPLETE_MARKERS):
                _startup_capture_enabled = False


def _store_log_entry(
    timestamp: str, level: str, message: str, *, forward: bool
) -> None:
    """Store a log entry in memory and optionally forward it cross-process."""
    entry = {"timestamp": timestamp, "level": level, "message": message}
    if hasattr(_thread_local, "color"):
        entry["thread_color"] = _thread_local.color
    if hasattr(_thread_local, "site") and _thread_local.site is not None:
        entry["thread_site"] = _thread_local.site

    _append_log_entry(entry)

    if forward and _log_forward_queue is not None:
        try:
            _log_forward_queue.put_nowait(entry)
        except Exception:
            pass


def mark_startup_complete() -> None:
    """Stop collecting startup log entries in this process."""
    global _startup_capture_enabled
    with _log_buffer_lock:
        _startup_capture_enabled = False


class bcolors:
    """Terminal ANSI color codes for colored console output."""

    HEADER = "\033[95m"  # Purple color for headers
    OKBLUE = "\033[94m"  # Blue color for informational messages
    OKGREEN = "\033[92m"  # Green color for success messages
    WARNING = "\033[93m"  # Yellow color for warnings
    FAIL = "\033[91m"  # Red color for errors and failures
    ENDC = "\033[0m"  # Reset/end color formatting
    BOLD = "\033[1m"  # Bold text formatting
    UNDERLINE = "\033[4m"  # Underline text formatting


# Color name to ANSI code mapping for dynamic color selection
color_map = {
    "HEADER": bcolors.HEADER,
    "OKBLUE": bcolors.OKBLUE,
    "OKGREEN": bcolors.OKGREEN,
    "WARNING": bcolors.WARNING,
    "FAIL": bcolors.FAIL,
    "ENDC": bcolors.ENDC,
    "BOLD": bcolors.BOLD,
    "UNDERLINE": bcolors.UNDERLINE,
}


# Process-local variables for global verbose and web logging control
class _LoggingFlag:
    """Lightweight process-local boolean flag providing a .value attribute."""

    def __init__(self, value: bool = False) -> None:
        self.value = bool(value)

    def __bool__(self) -> bool:
        return bool(self.value)

    def __repr__(self) -> str:
        return f"_LoggingFlag({self.value})"


verbose = _LoggingFlag(False)
web_enabled = _LoggingFlag(True)


def set_verbose(value: bool) -> None:
    """Sets the global verbose logging flag for debug output control."""
    verbose.value = value


def set_web_enabled(value: bool) -> None:
    """Sets whether the web UI is enabled for ring-buffer and debug log capture."""
    web_enabled.value = bool(value)


def is_web_enabled() -> bool:
    """Returns whether web UI log buffering is enabled."""
    return bool(web_enabled.value)


def set_log_forward_queue(queue: LogQueue | None) -> None:
    """Set (or clear) the cross-process log-forwarding queue.

    Call this once per process at startup.  When *queue* is not None
    every subsequent :func:`log` call will also put the entry onto the
    queue so the web-server process (which has a separate copy of
    ``_log_buffer``) can drain it and display logs from all processes.

    Any log entries that were emitted in this process prior to attaching
    the queue (such as early startup banners, tool versions, and configuration
    details) are automatically replayed into the queue so the web server captures
    the complete startup history.

    Pass ``None`` to disable forwarding (e.g. inside the web-server
    process itself so it does not re-push its own entries).

    Args:
        queue: A :class:`multiprocessing.Queue`-compatible object, or
               ``None`` to disable forwarding.
    """
    global _log_forward_queue
    _log_forward_queue = queue
    if queue is not None:
        with _log_buffer_lock:
            for entry in list(_log_buffer):
                try:
                    queue.put_nowait(entry)
                except Exception:
                    pass


def start_log_drain_thread(queue: LogQueue) -> threading.Thread:
    """Start a daemon thread that drains *queue* into the local ring buffer.

    Intended to be called once inside the web-server process so that log
    entries produced by all other processes (supervisor, worker pool, main)
    end up in this process's ``_log_buffer`` and are therefore returned by
    :func:`get_recent_logs`.

    Args:
        queue: The same queue that was passed to :func:`set_log_forward_queue`
               in every other process.

    Returns:
        The started daemon :class:`threading.Thread`.
    """

    def _drain() -> None:
        # Runs as a daemon thread; it exits naturally when the process dies or
        # when the underlying manager queue raises an exception (e.g. because
        # the Manager server process has shut down).
        while True:
            try:
                entry = queue.get(timeout=0.5)
                _append_log_entry(entry)
            except Empty:
                continue
            except Exception:
                # Queue closed or manager gone — stop draining.
                break

    t = threading.Thread(target=_drain, daemon=True, name="log-drain")
    t.start()
    return t


def is_verbose() -> bool:
    """Returns the current state of the global verbose logging flag."""
    return bool(verbose.value)


def set_thread_color(ansi_code: str) -> None:
    """Sets the color for the current thread's log output.

    Args:
        ansi_code: The ANSI escape sequence to use as the default color
                  for logs from this thread.
    """
    _thread_local.color = ansi_code


def init_process_logging(
    verbose_flag: bool,
    *,
    color: str | None = None,
    log_queue: LogQueue | None = None,
    config_store: object | None = None,
    is_web_server: bool = False,
) -> None:
    """Initialize logging for a spawned process.

    Centralizes verbose flag setup, thread color, web ring-buffer toggling,
    and cross-process log forwarding or draining.
    """
    set_verbose(verbose_flag)
    if color is not None:
        set_thread_color(color)

    if is_web_server:
        # The web server drains the cross-process log queue into its own ring buffer
        # rather than forwarding its own logs back onto the queue.
        set_log_forward_queue(None)
        if log_queue is not None:
            start_log_drain_thread(log_queue)
    else:
        if log_queue is not None:
            set_web_enabled(True)
        elif config_store is not None:
            set_web_enabled(False)
        set_log_forward_queue(log_queue)


def set_thread_site(site: str | None) -> None:
    """Sets (or clears) the site tag for the current thread's log output.

    While set, every log entry produced by this thread will carry a
    ``thread_site`` field so the web UI can filter logs by site without
    relying on regex parsing of message text.

    Args:
        site: Site identifier (e.g. ``"ao3"``, ``"fanfiction"``), or
              ``None`` to clear the tag (e.g. when a worker goes idle).
    """
    _thread_local.site = site


def get_color_for_worker(index: int) -> str:
    """Generates a unique ANSI 256-color code for a worker index.

    Selects from a curated list of high-contrast colors suitable for dark backgrounds,
    ensuring readability and consistency across worker instances.
    """
    # Curated list of 35 high-visibility ANSI 256 colors
    # selected for readability on dark backgrounds.
    # Includes: Blues, Cyans, Greens, Pinks, Purples, Oranges, Yellows
    # Curated list of 35 high-visibility ANSI 256 colors
    # manually interleaved to ensure high contrast between sequential workers.
    safe_colors = [
        210,  # Light Coral
        209,  # Salmon
        196,  # Red (Bright)
        39,  # Deep Sky Blue
        153,  # Light Cyan
        46,  # Green (Bright)
        201,  # Magenta
        51,  # Cyan
        118,  # Chartreuse
        226,  # Yellow
        141,  # Lavender
        49,  # Medium Spring Green
        75,  # Steel Blue
        220,  # Gold
        155,  # Pale Green
        213,  # Orchid
        81,  # Sky Blue
        99,  # Slate Blue
        219,  # Plum
        87,  # Dark Slate Gray (actually light cyan-ish)
        190,  # Yellow Green
        159,  # Pale Cyan
        207,  # Medium Orchid
        154,  # Green Yellow
        45,  # Turquoise
        86,  # Aquamarine
        123,  # Dark Sky Blue
        147,  # Light Steel Blue
        117,  # Light Blue
        85,  # Dark Sea Green
        208,  # Dark Orange
        192,  # Dark Olive Green (Light)
        120,  # Light Green
        212,  # Pink
        33,  # Dodger Blue
    ]

    # Cycle through the safe color list based on worker index
    color_code = safe_colors[index % len(safe_colors)]

    return f"\033[38;5;{color_code}m"


def log(
    msg: str, color: str = "", *, _level: str = "", _ring_buffer_only: bool = False
) -> None:
    """Logs a timestamped message to console with optional color formatting."""

    # Determine color:
    # 1. Explicit argument mapped name (e.g. "FAIL")
    # 2. Explicit argument raw ANSI code (if not in map)
    # 3. Thread-local default color
    # 4. Default BOLD

    using_col = bcolors.BOLD

    if color:
        using_col = color_map.get(color, color)
    elif hasattr(_thread_local, "color"):
        using_col = _thread_local.color

    # Determine log level for the ring buffer
    if _level:
        level = _level
    elif color == "FAIL":
        level = "error"
    elif color == "WARNING":
        level = "warning"
    else:
        level = "info"

    # Generate current timestamp in standardized format
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

    if not _ring_buffer_only:
        # Output formatted message with timestamp and color codes
        print(
            f"{bcolors.BOLD}{timestamp}{bcolors.ENDC} - {using_col}{msg}{bcolors.ENDC}",
            flush=True,
        )

    if web_enabled.value:
        _store_log_entry(timestamp, level, msg, forward=not _ring_buffer_only)


def log_failure(msg: str) -> None:
    """Logs an error or failure message in red color.

    Convenience function for logging error conditions, failures, and critical
    issues. Automatically applies red color formatting to make error messages
    visually distinct from other log output types.

    Args:
        msg (str): The failure or error message to log. Should describe the
                  specific error condition, failure reason, or critical issue
                  that occurred during application execution.

    Example:
        >>> log_failure("Database connection failed")
        >>> log_failure("Configuration file not found")
        >>> log_failure("Process terminated unexpectedly")
    """
    # Use the core log function with FAIL color for red error formatting
    log(msg, "FAIL")


def log_debug(msg: str) -> None:
    """Logs a debug message in blue color when verbose mode is enabled.

    Conditional logging function that only outputs debug messages to the console
    when the global verbose flag is True. When the web server is enabled, debug
    entries are always stored and forwarded to the web UI so they can be filtered
    or inspected for bug reports. When both verbose mode and the web server are
    disabled, this function returns immediately with zero formatting overhead.

    Args:
        msg (str): The debug message to log. Should contain detailed diagnostic
                  information, variable states, or execution flow details useful
                  for development and troubleshooting purposes.
    """
    is_verb = bool(verbose.value)
    is_web = bool(web_enabled.value)
    if not is_verb and not is_web:
        return

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

    if is_verb:
        using_col = getattr(_thread_local, "color", bcolors.BOLD)
        print(
            f"{bcolors.BOLD}{timestamp}{bcolors.ENDC} - {using_col}{msg}{bcolors.ENDC}",
            flush=True,
        )

    if is_web:
        _store_log_entry(timestamp, "debug", msg, forward=True)


def get_recent_logs(limit: int = 500) -> list[dict]:
    """Return the most recent log entries from the in-memory ring buffer.

    Args:
        limit: Maximum number of entries to return (most recent first).

    Returns:
        List of log entry dicts with keys: timestamp, level, message.
    """
    with _log_buffer_lock:
        # Return most recent entries, newest first
        entries = list(_log_buffer)
    entries.reverse()
    return entries[:limit]


def get_startup_logs(limit: int = 500) -> list[dict]:
    """Return startup-phase log entries from the in-memory startup buffer."""
    with _log_buffer_lock:
        entries = list(_startup_log_buffer)
    entries.reverse()
    return entries[:limit]
