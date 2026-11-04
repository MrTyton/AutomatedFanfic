"""Custom logging module for AutomatedFanfic application.

Provides colored console logging, thread-local execution context, an in-memory
ring buffer for the web UI, and rotating JSONL disk persistence.
"""

from ff_logging.buffer import (
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
from ff_logging.colors import (
    bcolors,
    color_map,
    get_color_for_worker,
)
from ff_logging.context import (
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
from ff_logging.core import (
    init_persistent_logging,
    init_process_logging,
    log,
    log_debug,
    log_failure,
)
from ff_logging.persistent import (
    close_persistent_logging,
    get_persistent_log_path,
    is_failure_entry,
    is_story_event,
    resolve_log_file_path,
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
    "resolve_log_file_path",
    "get_persistent_log_path",
    "is_story_event",
    "is_failure_entry",
    "init_process_logging",
    "log",
    "log_failure",
    "log_debug",
    "append_log_entry",
    "store_log_entry",
    "rehydrate_buffer",
]
