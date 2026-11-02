"""In-memory ring buffer and cross-process log forwarding for ff_logging."""

import collections
from queue import Empty
import threading

from ff_logging.persistent import (
    get_next_sequence_number,
    write_persistent_entry,
)
lazy from models.queue_types import LogQueue

_LOG_BUFFER_MAX = 2000
_log_buffer: collections.deque = collections.deque(maxlen=_LOG_BUFFER_MAX)
_log_buffer_lock = threading.Lock()

_STARTUP_LOG_BUFFER_MAX = 2000
_startup_log_buffer: collections.deque = collections.deque(
    maxlen=_STARTUP_LOG_BUFFER_MAX
)
_startup_capture_enabled = True
_startup_subsystems = {
    "core_ready": False,
    "web_expected": False,
    "web_ready": False,
    "email_expected": False,
    "email_ready": False,
}

_log_forward_queue: LogQueue | None = None


def _reset_startup_subsystems() -> None:
    _startup_subsystems["core_ready"] = False
    _startup_subsystems["web_expected"] = False
    _startup_subsystems["web_ready"] = False
    _startup_subsystems["email_expected"] = False
    _startup_subsystems["email_ready"] = False


def _update_startup_readiness(msg: str) -> bool:
    """Updates subsystem milestones and returns True when ALL expected systems are up."""
    lower = msg.lower()
    if "web dashboard enabled on" in lower or "web dashboard: enabled" in lower:
        _startup_subsystems["web_expected"] = True
    if "email account:" in lower and not any(
        kw in lower for kw in ("not configured", "disabled", "none")
    ):
        _startup_subsystems["email_expected"] = True

    if (
        "processes running. press ctrl+c" in lower
        or "all processes started successfully" in lower
    ):
        _startup_subsystems["core_ready"] = True
    if "webserver: history database connection established" in lower:
        _startup_subsystems["web_ready"] = True
    if any(
        kw in lower
        for kw in (
            "entered imap idle mode",
            "idle refresh timeout reached",
            "imap idle error",
            "unread email(s) before entering idle",
        )
    ):
        _startup_subsystems["email_ready"] = True

    return bool(
        _startup_subsystems["core_ready"]
        and (
            not _startup_subsystems["web_expected"] or _startup_subsystems["web_ready"]
        )
        and (
            not _startup_subsystems["email_expected"]
            or _startup_subsystems["email_ready"]
        )
    )


def append_log_entry(entry: dict) -> None:
    """Append an entry to runtime/startup buffers and write to disk if enabled."""
    global _startup_capture_enabled
    with _log_buffer_lock:
        if "seq" not in entry:
            entry["seq"] = get_next_sequence_number()
        if _startup_capture_enabled:
            entry["is_startup"] = True
            _startup_log_buffer.append(dict(entry))
            msg = str(entry.get("message", ""))
            if _update_startup_readiness(msg):
                _startup_capture_enabled = False
        _log_buffer.append(entry)

    write_persistent_entry(entry)


def rehydrate_buffer(entries: list[dict]) -> None:
    """Populate the in-memory ring buffer with entries rehydrated from disk."""
    with _log_buffer_lock:
        for entry in entries:
            _log_buffer.append(entry)


def store_log_entry(
    timestamp: str,
    level: str,
    msg: str,
    context: dict,
    forward: bool = True,
) -> None:
    """Build a log entry dict, store it locally, and optionally forward to the queue."""
    entry: dict = {
        "timestamp": timestamp,
        "level": level,
        "message": str(msg),
    }
    entry.update(context)

    if _log_forward_queue is not None and forward:
        try:
            _log_forward_queue.put_nowait(entry)
        except Exception:
            pass
    else:
        append_log_entry(entry)


def mark_startup_complete() -> None:
    """Mark startup log capture as completed."""
    global _startup_capture_enabled
    with _log_buffer_lock:
        _startup_capture_enabled = False


def set_log_forward_queue(queue: LogQueue | None) -> None:
    """Attach a multiprocessing Queue so logs from this process are forwarded to the web server."""
    global _log_forward_queue
    _log_forward_queue = queue
    if queue is not None:
        with _log_buffer_lock:
            early_entries = list(_log_buffer)
        for entry in early_entries:
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
    global _startup_capture_enabled
    with _log_buffer_lock:
        _log_buffer.clear()
        _startup_log_buffer.clear()
        _startup_capture_enabled = True
        _reset_startup_subsystems()
