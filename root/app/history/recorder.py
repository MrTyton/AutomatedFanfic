"""Cross-process history recording via mp.Queue.

HistoryRecorder is the facade used by every process/thread to emit events.
HistoryWriter is a daemon thread that drains the queue and writes to SQLite.
"""

from datetime import datetime, timezone

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
from models.queue_types import HistoryQueue


class HistoryRecorder:
    """Process-safe facade that puts event messages onto the history_queue.

    Every process/thread gets a reference to the same mp.Queue.
    Calls are non-blocking fire-and-forget.
    """

    def __init__(self, history_queue: HistoryQueue):
        self._queue = history_queue

    def _put(self, msg: HistoryMessage) -> None:
        try:
            self._queue.put_nowait(msg.model_dump())
        except Exception:
            # Never block or crash the pipeline for history recording
            pass

    # -- convenience methods --

    def record_download_created(
        self, url: str, site: str, behavior: str | None = None
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
        title: str | None = None,
        calibre_id: str | None = None,
        site: str | None = None,
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
        self, url: str, error_message: str | None = None, site: str | None = None
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
        self,
        url: str,
        error_message: str | None = None,
        site: str | None = None,
        title: str | None = None,
        calibre_id: str | None = None,
    ) -> None:
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.DOWNLOAD_UPDATED,
                payload={
                    "url": url,
                    "status": DownloadStatus.ABANDONED.value,
                    "error_message": error_message,
                    "site": site,
                    "title": title,
                    "calibre_id": calibre_id,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )

    def record_download_processing(self, url: str, site: str | None = None) -> None:
        """Move an existing 'pending' download row to 'processing' status."""
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.DOWNLOAD_UPDATED,
                payload={
                    "url": url,
                    "status": DownloadStatus.PROCESSING.value,
                    "site": site,
                },
            )
        )

    def record_download_waiting(
        self,
        url: str,
        site: str | None = None,
        title: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Called when download is queued for retry with backoff delay."""
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.DOWNLOAD_UPDATED,
                payload={
                    "url": url,
                    "status": DownloadStatus.WAITING.value,
                    "site": site,
                    "title": title,
                    "error_message": error_message,
                },
            )
        )

    def record_download_requeued(
        self,
        url: str,
        site: str | None = None,
        title: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Move an existing download row back to 'pending' status.

        Used when a user manually retries a URL from the web UI or when
        uncompleted downloads are rehydrated on startup. Updates the
        existing row rather than inserting a duplicate.
        """
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.DOWNLOAD_UPDATED,
                payload={
                    "url": url,
                    "status": DownloadStatus.PENDING.value,
                    "site": site,
                    "title": title,
                    "error_message": error_message,
                },
            )
        )

    def record_download_title_update(
        self, url: str, title: str, site: str | None = None
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
        error_message: str | None = None,
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
        trigger: str = "poll",
    ) -> None:
        self._put(
            HistoryMessage(
                event_type=HistoryEventType.EMAIL_CHECK,
                payload=EmailCheckEvent(
                    urls_found=urls_found,
                    urls_new=urls_new,
                    urls_duplicate=urls_duplicate,
                    urls_disabled_site=urls_disabled_site,
                    trigger=trigger,
                ).model_dump(mode="json"),
            )
        )

    def record_notification(
        self,
        title: str,
        body: str,
        site: str | None = None,
        provider: str | None = None,
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


__all__ = ["HistoryRecorder"]
