"""Pydantic models for history event records.

Defines the data structures for all events tracked by the history system:
download lifecycle, retry attempts, email checks, and notifications.
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DownloadStatus(str, Enum):
    """Status of a download event throughout its lifecycle."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    WAITING = "waiting"
    ABANDONED = "abandoned"


class RetryAction(str, Enum):
    """The action taken on a retry event, mirroring FailureAction."""

    RETRY = "retry"
    HAIL_MARY = "hail_mary"
    ABANDON = "abandon"


class DownloadEvent(BaseModel):
    """A fanfiction download lifecycle event.

    Created when a URL enters the pipeline (status=pending), updated on
    completion (success/failed/abandoned).
    """

    id: int | None = None
    url: str
    site: str
    title: str | None = None
    calibre_id: str | None = None
    behavior: str | None = None
    status: DownloadStatus = DownloadStatus.PENDING
    error_message: str | None = None
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None


class RetryEvent(BaseModel):
    """A single retry attempt for a download."""

    id: int | None = None
    download_event_id: int | None = None
    url: str
    site: str
    attempt_number: int
    action: RetryAction
    delay_minutes: float = 0.0
    error_message: str | None = None
    scheduled_at: datetime = Field(default_factory=_utcnow)
    fired_at: datetime | None = None


class EmailCheckEvent(BaseModel):
    """Record of a single email polling cycle."""

    id: int | None = None
    checked_at: datetime = Field(default_factory=_utcnow)
    urls_found: int = 0
    urls_new: int = 0
    urls_duplicate: int = 0
    urls_disabled_site: int = 0
    trigger: str = "poll"  # "poll" or "idle"


class NotificationEvent(BaseModel):
    """Record of a notification sent via Apprise/Pushbullet."""

    id: int | None = None
    download_event_id: int | None = None
    title: str
    body: str
    site: str | None = None
    sent_at: datetime = Field(default_factory=_utcnow)
    provider: str | None = None


# --- Wire format for cross-process history_queue messages ---


class HistoryEventType(str, Enum):
    """Discriminator for events sent over the history_queue."""

    DOWNLOAD_CREATED = "download_created"
    DOWNLOAD_UPDATED = "download_updated"
    RETRY = "retry"
    RETRY_FIRED = "retry_fired"
    EMAIL_CHECK = "email_check"
    NOTIFICATION = "notification"


class HistoryMessage(BaseModel):
    """Envelope sent over the mp.Queue to the HistoryWriter thread.

    Uses event_type as discriminator so the writer knows which table to target.
    The payload is a dict matching the corresponding event model's fields.
    """

    event_type: HistoryEventType
    payload: dict
