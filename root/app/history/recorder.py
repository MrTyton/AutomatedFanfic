"""Cross-process history recording via mp.Queue.

HistoryRecorder is the facade used by every process/thread to emit events.
HistoryWriter is a daemon thread that drains the queue and writes to SQLite.
"""

import multiprocessing
import threading
from datetime import datetime, timezone
from queue import Empty
from typing import Optional

from history.database import SyncHistoryDB
from history.models import (
    DownloadEvent,
    DownloadStatus,
    EmailCheckEvent,
    HistoryEventType,
    HistoryMessage,
    NotificationEvent,
    RetryAction,
    RetryEvent,
)
from utils import ff_logging


class HistoryRecorder:
    """Process-safe facade that puts event messages onto the history_queue.

    Every process/thread gets a reference to the same mp.Queue.
    Calls are non-blocking fire-and-forget.
    """

    def __init__(self, history_queue: multiprocessing.Queue):  # type: ignore[type-arg]
        self._queue = history_queue

    def _put(self, msg: HistoryMessage) -> None:
        try:
            self._queue.put_nowait(msg.model_dump())
        except Exception:
            # Never block or crash the pipeline for history recording
            pass

    # -- convenience methods --

    def record_download_created(
        self, url: str, site: str, behavior: Optional[str] = None
    ) -> None:
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.DOWNLOAD_CREATED,
                payload=DownloadEvent(
                    url=url,
                    site=site,
                    behavior=behavior,
                ).model_dump(mode="json"),
            )
        )

    def record_download_success(
        self,
        url: str,
        title: Optional[str] = None,
        calibre_id: Optional[str] = None,
        site: Optional[str] = None,
    ) -> None:
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.DOWNLOAD_UPDATED,
                payload={
                    "url": url,
                    "status": DownloadStatus.SUCCESS.value,
                    "title": title,
                    "calibre_id": calibre_id,
                    "site": site,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )

    def record_download_failed(
        self, url: str, error_message: Optional[str] = None, site: Optional[str] = None
    ) -> None:
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.DOWNLOAD_UPDATED,
                payload={
                    "url": url,
                    "status": DownloadStatus.FAILED.value,
                    "error_message": error_message,
                    "site": site,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )

    def record_download_abandoned(
        self, url: str, error_message: Optional[str] = None, site: Optional[str] = None
    ) -> None:
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.DOWNLOAD_UPDATED,
                payload={
                    "url": url,
                    "status": DownloadStatus.ABANDONED.value,
                    "error_message": error_message,
                    "site": site,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )

    def record_download_waiting(self, url: str, site: Optional[str] = None) -> None:
        """Called when download is queued for retry with backoff delay."""
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.DOWNLOAD_UPDATED,
                payload={
                    "url": url,
                    "status": DownloadStatus.WAITING.value,
                    "site": site,
                },
            )
        )

    def record_download_title_update(
        self, url: str, title: str, site: Optional[str] = None
    ) -> None:
        """Update the title on a pending download row without changing status."""
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.DOWNLOAD_UPDATED,
                payload={
                    "url": url,
                    "status": DownloadStatus.PENDING.value,
                    "title": title,
                    "site": site,
                },
            )
        )

    def record_retry(
        self,
        url: str,
        site: str,
        attempt_number: int,
        action: str,
        delay_minutes: float = 0.0,
        error_message: Optional[str] = None,
    ) -> None:
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.RETRY,
                payload=RetryEvent(
                    url=url,
                    site=site,
                    attempt_number=attempt_number,
                    action=RetryAction(action),
                    delay_minutes=delay_minutes,
                    error_message=error_message,
                ).model_dump(mode="json"),
            )
        )

    def record_retry_fired(self, url: str, attempt_number: int) -> None:
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.RETRY_FIRED,
                payload={
                    "url": url,
                    "attempt_number": attempt_number,
                    "fired_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )

    def record_email_check(
        self,
        urls_found: int = 0,
        urls_new: int = 0,
        urls_duplicate: int = 0,
        urls_disabled_site: int = 0,
    ) -> None:
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.EMAIL_CHECK,
                payload=EmailCheckEvent(
                    urls_found=urls_found,
                    urls_new=urls_new,
                    urls_duplicate=urls_duplicate,
                    urls_disabled_site=urls_disabled_site,
                ).model_dump(mode="json"),
            )
        )

    def record_notification(
        self,
        title: str,
        body: str,
        site: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> None:
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.NOTIFICATION,
                payload=NotificationEvent(
                    title=title,
                    body=body,
                    site=site,
                    provider=provider,
                ).model_dump(mode="json"),
            )
        )


class HistoryWriter:
    """Daemon thread that drains history_queue and writes to SQLite.

    Runs as a single writer — no SQLite concurrency issues.
    """

    def __init__(
        self,
        history_queue: multiprocessing.Queue,  # type: ignore[type-arg]
        db_path: str,
        shutdown_event: Optional[threading.Event] = None,
    ):
        self._queue = history_queue
        self._db_path = db_path
        self._shutdown = shutdown_event or threading.Event()
        self._db: Optional[SyncHistoryDB] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="HistoryWriter", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._shutdown.set()
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
                except OSError:
                    break
                self._process_message(raw)
            # Drain remaining messages on shutdown
            self._drain()
        finally:
            if self._db:
                self._db.close()
            ff_logging.log("HistoryWriter: stopped")

    def _drain(self) -> None:
        while True:
            try:
                raw = self._queue.get_nowait()
            except (Empty, OSError):
                break
            self._process_message(raw)

    def _process_message(self, raw: dict) -> None:
        try:
            msg = HistoryMessage(**raw)
            payload = msg.payload
            et = msg.event_type
            assert self._db is not None

            if et == HistoryEventType.DOWNLOAD_CREATED:
                event = DownloadEvent(**payload)
                self._db.insert_download(event)

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
                )

            elif et == HistoryEventType.RETRY:
                event = RetryEvent(**payload)
                self._db.insert_retry(event)

            elif et == HistoryEventType.RETRY_FIRED:
                self._db.update_retry_fired(
                    url=payload["url"],
                    attempt_number=payload["attempt_number"],
                    fired_at=datetime.fromisoformat(payload["fired_at"]),
                )

            elif et == HistoryEventType.EMAIL_CHECK:
                event = EmailCheckEvent(**payload)
                self._db.insert_email_check(event)

            elif et == HistoryEventType.NOTIFICATION:
                event = NotificationEvent(**payload)
                self._db.insert_notification(event)

        except Exception as e:
            ff_logging.log_failure(f"HistoryWriter: error processing message: {e}")
