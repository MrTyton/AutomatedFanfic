"""Persistent JSONL log file handler and disk rotation for ff_logging."""

import json
import logging
import logging.handlers
from pathlib import Path
import threading

lazy from utils import system_utils

_persistent_logger = logging.getLogger("automatedfanfic.persistent")
_persistent_logger.setLevel(logging.INFO)
_persistent_logger.propagate = False
_persistent_handler: logging.handlers.RotatingFileHandler | None = None
_persistent_log_lock = threading.Lock()
_persistent_log_path: str | None = None


def get_persistent_log_path() -> str | None:
    """Return the absolute path to the active persistent JSONL log file, if any."""
    with _persistent_log_lock:
        return _persistent_log_path


_log_seq_lock = threading.Lock()
_log_seq_counter = 0


def resolve_log_file_path(
    log_file_path: str | None,
    history_db_path: str | None,
) -> str | None:
    """Resolve persistent log file path, co-locating alongside history_db_path or /config when using default /data path."""
    if not isinstance(log_file_path, str) or not log_file_path.strip():
        return None
    if log_file_path == "/data/automatedfanfic.log" and (
        (history_db_path and not str(history_db_path).startswith("/data/"))
        or (system_utils.is_docker_environment() and Path("/config").exists())
    ):
        target_dir = (
            Path(history_db_path).parent
            if history_db_path and not str(history_db_path).startswith("/data/")
            else Path("/config")
        )
        return str(target_dir / "automatedfanfic.log")
    return log_file_path


def get_next_sequence_number() -> int:
    """Generate and return the next monotonically increasing log sequence number."""
    global _log_seq_counter
    with _log_seq_lock:
        _log_seq_counter += 1
        return _log_seq_counter


def update_sequence_watermark(seq: int) -> None:
    """Advance the log sequence counter if the given sequence number is higher."""
    global _log_seq_counter
    with _log_seq_lock:
        if seq > _log_seq_counter:
            _log_seq_counter = seq


def is_failure_entry(entry: dict) -> bool:
    """Return True if an entry represents or contains a failure/warning/error.

    Used by persistent disk logging to only record events that encountered
    failures or errors, omitting routine successes that had no problems.
    """
    if not isinstance(entry, dict):
        return False

    level = str(entry.get("level", "")).lower()
    if level in ("error", "failure", "warning", "warn", "critical"):
        return True

    msg = str(entry.get("message", "")).strip()
    msg_lower = msg.lower()

    if any(
        kw in msg_lower
        for kw in (
            "fail",
            "error",
            "exception",
            "crashed",
            "retry",
            "abandon",
            "warning",
            "warn:",
            "fail:",
            "forceable:",
            "tab crashed",
            "timeout",
        )
    ):
        return True

    return False


def is_story_event(entry: dict) -> bool:
    """Return True if a log entry is related to story downloading or processing.

    Only story events are rehydrated into the live in-memory buffer on startup.
    System lifecycle, startup banners, shutdown signals, and background infrastructure
    logs from prior runs are omitted from live rehydration.
    """
    if not isinstance(entry, dict):
        return False
    if (
        entry.get("story_url")
        or entry.get("attempt_id")
        or entry.get("story_title")
        or entry.get("thread_site")
    ):
        return True

    msg = str(entry.get("message", "")).strip()
    msg_lower = msg.lower()

    # Explicitly exclude system startup/shutdown/infrastructure messages
    if (
        entry.get("is_startup")
        or msg_lower.startswith("starting automatedfanfic")
        or msg_lower.startswith("for issues and updates")
        or msg_lower.startswith("using configuration file")
        or msg_lower.startswith("python version:")
        or msg_lower.startswith("os / platform:")
        or msg_lower.startswith("calibre version:")
        or msg_lower.startswith("fanficfare version:")
        or msg_lower.startswith("apprise version:")
        or "configuration details" in msg_lower
        or msg_lower.startswith("generating url parsers")
        or msg_lower.startswith("spawning ")
        or msg_lower.startswith("all processes started")
        or msg_lower.startswith("processes running")
        or msg_lower.startswith("received signal sig")
        or msg_lower.startswith("coordinator received shutdown signal")
        or msg_lower.startswith("webserver:")
        or msg_lower.startswith("historywriter:")
        or msg_lower.startswith("supervisor: waiting for threads")
        or msg_lower.startswith("supervisor: starting helper services")
    ):
        return False

    # Check for story processing indicators
    if (
        "processing http" in msg_lower
        or "processing (" in msg_lower
        or "extracted title" in msg_lower
        or "updating /tmp/" in msg_lower
        or "executing fanficfare" in msg_lower
        or "story is in calibre" in msg_lower
        or "added book ids:" in msg_lower
        or "successfully processed" in msg_lower
        or "failed to download" in msg_lower
        or "failed to process" in msg_lower
        or "notification dispatched" in msg_lower
        or "notification for 'new fanfiction download'" in msg_lower
        or ("adding " in msg_lower and "to the ingestion queue" in msg_lower)
    ):
        return True

    return False


def init_persistent_logging(
    log_path: str | None,
    max_bytes: int = 5_000_000,
    backup_count: int = 3,
) -> list[dict]:
    """Initialize persistent rotating JSONL log file and return rehydratable story entries."""
    global _persistent_handler, _persistent_log_path
    if not isinstance(log_path, str) or not log_path.strip():
        return []

    close_persistent_logging()

    path_obj = Path(log_path)
    try:
        path_obj.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    rehydrated_entries: list[dict] = []
    # Rehydrate existing entries from disk if file exists (story events only)
    if path_obj.exists():
        try:
            with open(path_obj, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            for line in lines[-2000:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict) and "message" in data:
                        seq = data.get("seq")
                        if isinstance(seq, int):
                            update_sequence_watermark(seq)
                        if is_story_event(data):
                            rehydrated_entries.append(data)
                except Exception:
                    continue
        except Exception:
            pass

    with _persistent_log_lock:
        try:
            handler = logging.handlers.RotatingFileHandler(
                str(path_obj),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            _persistent_logger.handlers.clear()
            _persistent_logger.addHandler(handler)
            _persistent_handler = handler
            _persistent_log_path = str(path_obj)
        except Exception:
            _persistent_handler = None
            _persistent_log_path = None

    return rehydrated_entries


def close_persistent_logging() -> None:
    """Close and flush the persistent log handler."""
    global _persistent_handler, _persistent_log_path
    with _persistent_log_lock:
        if _persistent_handler is not None:
            try:
                _persistent_handler.flush()
                _persistent_handler.close()
            except Exception:
                pass
            _persistent_logger.handlers.clear()
            _persistent_handler = None
            _persistent_log_path = None


def write_persistent_entry(entry: dict) -> None:
    """Write an entry to the persistent JSONL file handler if active and failure-related.

    Only entries that have errors, failures, retries, warnings, or exceptions are persisted
    to disk, omitting routine successes that had no problems.
    """
    if _persistent_handler is not None and is_failure_entry(entry):
        with _persistent_log_lock:
            if _persistent_handler is not None:
                try:
                    line = json.dumps(entry, ensure_ascii=False)
                    _persistent_logger.info(line)
                except Exception:
                    pass
