"""In-memory ring buffer and cross-process log forwarding for ff_logging."""

import collections
from queue import Empty
import threading
from typing import TYPE_CHECKING

from ff_logging.persistent import (
    get_next_sequence_number,
    write_persistent_entry,
)

if TYPE_CHECKING:
    from models.queue_types import LogQueue

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
    "WebServer: History database connection established",
)

_log_forward_queue: LogQueue | None = None


def append_log_entry(entry: dict) -> None:
    """Append an entry to runtime/startup buffers and write to disk if enabled."""
    global _startup_capture_enabled
    message = str(entry.get("message", ""))

    with _log_buffer_lock:
        if "seq" not in entry:
            entry["seq"] = get_next_sequence_number()
        if _startup_capture_enabled:
            entry["is_startup"] = True
            _startup_log_buffer.append(entry)
            if any(marker in message for marker in _STARTUP_COMPLETE_MARKERS):
                _startup_capture_enabled = False
        _log_buffer.append(entry)

    write_persistent_entry(entry)


def store_log_entry(
    timestamp: str,
    level: str,
    message: str,
    *,
    context: dict[str, object] | None = None,
    forward: bool = True,
) -> None:
    """Store a log entry in memory and optionally forward it cross-process."""
    entry: dict[str, object] = {
        "timestamp": timestamp,
        "level": level,
        "message": message,
    }
    if context:
        entry.update(context)

    append_log_entry(entry)

    if forward and _log_forward_queue is not None:
        try:
            _log_forward_queue.put_nowait(entry)
        except Exception:
            pass


def rehydrate_buffer(entries: list[dict]) -> None:
    """Rehydrate in-memory ring buffer with persistent entries from disk."""
    with _log_buffer_lock:
        for entry in entries:
            _log_buffer.append(entry)


def mark_startup_complete() -> None:
    """Stop collecting startup log entries in this process."""
    global _startup_capture_enabled
    with _log_buffer_lock:
        _startup_capture_enabled = False


def set_log_forward_queue(queue: LogQueue | None) -> None:
    """Set (or clear) the cross-process log-forwarding queue."""
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
    """Start a daemon thread that drains *queue* into the local ring buffer."""

    def _drain() -> None:
        while True:
            try:
                entry = queue.get(timeout=0.5)
                append_log_entry(entry)
            except Empty:
                continue
            except Exception:
                break

    t = threading.Thread(target=_drain, daemon=True, name="log-drain")
    t.start()
    return t


def get_recent_logs(limit: int = 500) -> list[dict]:
    """Return the most recent log entries from the in-memory ring buffer."""
    with _log_buffer_lock:
        entries = list(_log_buffer)
    entries.reverse()
    return entries[:limit]


def get_startup_logs(limit: int = 500) -> list[dict]:
    """Return startup-phase log entries from the in-memory startup buffer."""
    with _log_buffer_lock:
        entries = list(_startup_log_buffer)
    entries.reverse()
    return entries[:limit]


def clear_logs() -> None:
    """Clear all in-memory runtime and startup log buffers."""
    with _log_buffer_lock:
        _log_buffer.clear()
        _startup_log_buffer.clear()
