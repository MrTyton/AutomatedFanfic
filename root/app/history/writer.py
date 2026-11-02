"""Single-threaded background SQLite writer consuming events from history_queue."""

from __future__ import annotations

from datetime import datetime
from queue import Empty
import threading

import ff_logging
from history.models import (
    DownloadEvent,
    DownloadStatus,
    EmailCheckEvent,
    HistoryEventType,
    HistoryMessage,
    NotificationEvent,
    RetryEvent,
)
from history.sync_db import SyncHistoryDB
from models.queue_types import HistoryQueue


class HistoryWriter:
    """Daemon thread that drains history_queue and writes to SQLite.

    Runs as a single writer — no SQLite concurrency issues.
    """

    def __init__(
        self,
        history_queue: HistoryQueue,
        db_path: str,
        shutdown_event: threading.Event | None = None,
    ):
        self._queue = history_queue
        self._db_path = db_path
        self._shutdown = shutdown_event or threading.Event()
        self._db: SyncHistoryDB | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="HistoryWriter", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._shutdown.set()
        try:
            self._queue.put_nowait(None)  # type: ignore[arg-type]
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        self._db = SyncHistoryDB(self._db_path)
        self._db.connect()
        ff_logging.log("HistoryWriter: started")
        try:
            while not self._shutdown.is_set():
                try:
                    raw = self._queue.get(timeout=1.0)
                except Empty:
                    continue
                except OSError, EOFError:
                    break
                if raw is None:
                    break
                self._process_message(raw, commit=False)
                # Drain any immediately queued messages to commit in a single transaction
                for _ in range(49):
                    try:
                        next_raw = self._queue.get_nowait()
                    except Empty, OSError, EOFError:
                        break
                    if next_raw is None:
                        break
                    self._process_message(next_raw, commit=False)
                self._commit_safely()
            # Drain remaining messages on shutdown
            self._drain()
        finally:
            if self._db:
                self._db.close()
            ff_logging.log("HistoryWriter: stopped")

    def _drain(self) -> None:
        processed = False
        while True:
            try:
                raw = self._queue.get_nowait()
            except Empty, OSError, EOFError:
                break
            if raw is None:
                continue
            self._process_message(raw, commit=False)
            processed = True
        if processed:
            self._commit_safely()

    def _commit_safely(self) -> None:
        try:
            if self._db is not None and self._db._conn is not None:
                self._db._conn.commit()
        except Exception as e:
            ff_logging.log_failure(f"HistoryWriter: error committing batch: {e}")

    def _process_message(self, raw: dict, *, commit: bool = True) -> None:
        try:
            msg = HistoryMessage(**raw)
            payload = msg.payload
            et = msg.event_type
            assert self._db is not None

            if et == HistoryEventType.DOWNLOAD_CREATED:
                event = DownloadEvent(**payload)
                self._db.insert_download(event, commit=commit)

            elif et == HistoryEventType.DOWNLOAD_UPDATED:
                self._db.update_download(
                    url=payload["url"],
                    status=DownloadStatus(payload["status"]),
                    title=payload.get("title"),
                    calibre_id=payload.get("calibre_id"),
                    error_message=payload.get("error_message"),
                    completed_at=(
                        datetime.fromisoformat(payload["completed_at"])
                        if payload.get("completed_at")
                        else None
                    ),
                    site=payload.get("site"),
                    commit=commit,
                )

            elif et == HistoryEventType.RETRY:
                event = RetryEvent(**payload)
                self._db.insert_retry(event, commit=commit)

            elif et == HistoryEventType.RETRY_FIRED:
                self._db.update_retry_fired(
                    url=payload["url"],
                    attempt_number=payload["attempt_number"],
                    fired_at=datetime.fromisoformat(payload["fired_at"]),
                    commit=commit,
                )

            elif et == HistoryEventType.EMAIL_CHECK:
                event = EmailCheckEvent(**payload)
                self._db.insert_email_check(event, commit=commit)

            elif et == HistoryEventType.NOTIFICATION:
                event = NotificationEvent(**payload)
                self._db.insert_notification(event, commit=commit)

        except Exception as e:
            ff_logging.log_failure(f"HistoryWriter: error processing message: {e}")
