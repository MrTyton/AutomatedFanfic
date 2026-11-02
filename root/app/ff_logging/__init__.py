"""Custom logging module for AutomatedFanfic application.

Provides colored console logging, thread-local execution context, an in-memory
ring buffer for the web UI, and rotating JSONL disk persistence.
"""

import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.queue_types import LogQueue

# Import submodules so that ff_logging.colors, ff_logging.context, etc. exist
from ff_logging.colors import (
    bcolors,
    color_map,
    get_color_for_worker,
)
from ff_logging.context import (
    _thread_local,
    clear_thread_task,
    get_thread_color,
    get_thread_context,
    is_verbose,
    is_web_enabled,
    set_thread_color,
    set_thread_site,
    set_thread_story_title,
    set_thread_task,
    set_verbose,
    set_web_enabled,
    verbose,
    web_enabled,
)
from ff_logging.persistent import (
    close_persistent_logging,
    init_persistent_logging as _init_persistent,
    is_story_event,
)
from ff_logging.buffer import (
    _LOG_BUFFER_MAX,
    _STARTUP_COMPLETE_MARKERS,
    _STARTUP_LOG_BUFFER_MAX,
    _log_buffer,
    _log_buffer_lock,
    _log_forward_queue,
    _startup_capture_enabled,
    _startup_log_buffer,
    append_log_entry,
    clear_logs,
    get_recent_logs,
    get_startup_logs,
    mark_startup_complete,
    rehydrate_buffer,
    set_log_forward_queue,
    start_log_drain_thread,
    store_log_entry,
)


def init_persistent_logging(
    log_path: str | None,
    max_bytes: int = 5_000_000,
    backup_count: int = 3,
) -> None:
    """Initialize persistent rotating JSONL log file and rehydrate in-memory ring buffer."""
    rehydrated = _init_persistent(
        log_path, max_bytes=max_bytes, backup_count=backup_count
    )
    if rehydrated:
        rehydrate_buffer(rehydrated)


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


def log(
    msg: str, color: str = "", *, _level: str = "", _ring_buffer_only: bool = False
) -> None:
    """Logs a timestamped message to console with optional color formatting."""
    using_col = bcolors.BOLD

    if color:
        using_col = color_map.get(color, color)
    else:
        thread_col = get_thread_color()
        if thread_col is not None:
            using_col = thread_col

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
        print(
            f"{bcolors.BOLD}{timestamp}{bcolors.ENDC} - {using_col}{msg}{bcolors.ENDC}",
            flush=True,
        )

    if web_enabled.value:
        store_log_entry(
            timestamp,
            level,
            msg,
            context=get_thread_context(),
            forward=not _ring_buffer_only,
        )


def log_failure(msg: str) -> None:
    """Logs an error or failure message in red color."""
    log(msg, "FAIL")


def log_debug(msg: str) -> None:
    """Logs a debug message when verbose mode or web UI is enabled."""
    is_verb = bool(verbose.value)
    is_web = bool(web_enabled.value)
    if not is_verb and not is_web:
        return

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

    if is_verb:
        using_col = get_thread_color() or bcolors.BOLD
        print(
            f"{bcolors.BOLD}{timestamp}{bcolors.ENDC} - {using_col}{msg}{bcolors.ENDC}",
            flush=True,
        )

    if is_web:
        store_log_entry(
            timestamp,
            "debug",
            msg,
            context=get_thread_context(),
            forward=True,
        )


__all__ = [
    "bcolors",
    "color_map",
    "get_color_for_worker",
    "verbose",
    "web_enabled",
    "set_verbose",
    "is_verbose",
    "set_web_enabled",
    "is_web_enabled",
    "set_thread_color",
    "get_thread_color",
    "set_thread_site",
    "set_thread_task",
    "set_thread_story_title",
    "clear_thread_task",
    "get_thread_context",
    "get_recent_logs",
    "get_startup_logs",
    "clear_logs",
    "mark_startup_complete",
    "set_log_forward_queue",
    "start_log_drain_thread",
    "init_persistent_logging",
    "close_persistent_logging",
    "is_story_event",
    "init_process_logging",
    "log",
    "log_failure",
    "log_debug",
    "_thread_local",
    "_log_buffer",
    "_log_buffer_lock",
    "_startup_log_buffer",
    "_startup_capture_enabled",
    "_log_forward_queue",
    "_LOG_BUFFER_MAX",
    "_STARTUP_LOG_BUFFER_MAX",
    "_STARTUP_COMPLETE_MARKERS",
    "append_log_entry",
    "store_log_entry",
    "rehydrate_buffer",
]
