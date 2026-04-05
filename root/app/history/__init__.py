"""History subsystem for persistent event recording.

Provides cross-process event recording via mp.Queue and SQLite storage.
"""

from history.database import AsyncHistoryDB, SyncHistoryDB
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
from history.recorder import HistoryRecorder, HistoryWriter

__all__ = [
    "AsyncHistoryDB",
    "SyncHistoryDB",
    "DownloadEvent",
    "DownloadStatus",
    "EmailCheckEvent",
    "HistoryEventType",
    "HistoryMessage",
    "HistoryRecorder",
    "HistoryWriter",
    "NotificationEvent",
    "RetryAction",
    "RetryEvent",
]
