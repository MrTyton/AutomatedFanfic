"""History tracking package providing persistent database storage and queue recorder."""

from history.async_db import AsyncHistoryDB
from history.models import (
    DownloadEvent,
    DownloadStatus,
    EmailCheckEvent,
    NotificationEvent,
    RetryAction,
    RetryEvent,
)
from history.recorder import HistoryRecorder
from history.sync_db import SyncHistoryDB
from history.writer import HistoryWriter

__all__ = [
    "AsyncHistoryDB",
    "DownloadEvent",
    "DownloadStatus",
    "EmailCheckEvent",
    "HistoryRecorder",
    "HistoryWriter",
    "NotificationEvent",
    "RetryAction",
    "RetryEvent",
    "SyncHistoryDB",
]
