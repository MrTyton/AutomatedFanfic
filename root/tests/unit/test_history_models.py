"""Unit tests for history event models."""

import unittest
from datetime import datetime

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


class TestDownloadEvent(unittest.TestCase):
    def test_defaults(self):
        event = DownloadEvent(url="https://ao3.org/works/1", site="ao3")
        self.assertIsNone(event.id)
        self.assertEqual(event.url, "https://ao3.org/works/1")
        self.assertEqual(event.site, "ao3")
        self.assertIsNone(event.title)
        self.assertIsNone(event.calibre_id)
        self.assertIsNone(event.behavior)
        self.assertEqual(event.status, DownloadStatus.PENDING)
        self.assertIsNone(event.error_message)
        self.assertIsInstance(event.started_at, datetime)
        self.assertIsNone(event.completed_at)

    def test_full_fields(self):
        now = datetime(2026, 1, 1, 12, 0, 0)
        event = DownloadEvent(
            id=42,
            url="https://ffnet.com/s/1",
            site="ffnet",
            title="Test Story",
            calibre_id="99",
            behavior="force",
            status=DownloadStatus.SUCCESS,
            error_message=None,
            started_at=now,
            completed_at=now,
        )
        self.assertEqual(event.id, 42)
        self.assertEqual(event.status, DownloadStatus.SUCCESS)
        self.assertEqual(event.completed_at, now)

    def test_serialization_roundtrip(self):
        event = DownloadEvent(url="https://ao3.org/works/1", site="ao3")
        data = event.model_dump(mode="json")
        restored = DownloadEvent(**data)
        self.assertEqual(restored.url, event.url)
        self.assertEqual(restored.status, event.status)


class TestRetryEvent(unittest.TestCase):
    def test_defaults(self):
        event = RetryEvent(
            url="https://ao3.org/works/1",
            site="ao3",
            attempt_number=3,
            action=RetryAction.RETRY,
        )
        self.assertEqual(event.attempt_number, 3)
        self.assertEqual(event.action, RetryAction.RETRY)
        self.assertEqual(event.delay_minutes, 0.0)
        self.assertIsNone(event.fired_at)

    def test_hail_mary(self):
        event = RetryEvent(
            url="u",
            site="s",
            attempt_number=11,
            action=RetryAction.HAIL_MARY,
            delay_minutes=720.0,
        )
        self.assertEqual(event.action, RetryAction.HAIL_MARY)
        self.assertEqual(event.delay_minutes, 720.0)


class TestEmailCheckEvent(unittest.TestCase):
    def test_defaults(self):
        event = EmailCheckEvent()
        self.assertEqual(event.urls_found, 0)
        self.assertEqual(event.urls_new, 0)
        self.assertEqual(event.urls_duplicate, 0)
        self.assertEqual(event.urls_disabled_site, 0)
        self.assertIsInstance(event.checked_at, datetime)

    def test_counts(self):
        event = EmailCheckEvent(
            urls_found=5, urls_new=3, urls_duplicate=1, urls_disabled_site=1
        )
        self.assertEqual(event.urls_found, 5)
        self.assertEqual(event.urls_new, 3)


class TestNotificationEvent(unittest.TestCase):
    def test_required_fields(self):
        event = NotificationEvent(title="Success", body="Downloaded story X")
        self.assertEqual(event.title, "Success")
        self.assertEqual(event.body, "Downloaded story X")
        self.assertIsNone(event.site)
        self.assertIsNone(event.provider)

    def test_full_fields(self):
        event = NotificationEvent(
            title="t",
            body="b",
            site="ao3",
            provider="apprise",
            download_event_id=5,
        )
        self.assertEqual(event.download_event_id, 5)
        self.assertEqual(event.provider, "apprise")


class TestHistoryMessage(unittest.TestCase):
    def test_envelope_roundtrip(self):
        msg = HistoryMessage(
            event_type=HistoryEventType.DOWNLOAD_CREATED,
            payload={"url": "https://ao3.org/works/1", "site": "ao3"},
        )
        data = msg.model_dump()
        restored = HistoryMessage(**data)
        self.assertEqual(restored.event_type, HistoryEventType.DOWNLOAD_CREATED)
        self.assertEqual(restored.payload["url"], "https://ao3.org/works/1")

    def test_all_event_types(self):
        expected = {
            "download_created",
            "download_updated",
            "retry",
            "retry_fired",
            "email_check",
            "notification",
        }
        actual = {e.value for e in HistoryEventType}
        self.assertEqual(actual, expected)


class TestDownloadStatus(unittest.TestCase):
    def test_values(self):
        self.assertEqual(DownloadStatus.PENDING.value, "pending")
        self.assertEqual(DownloadStatus.SUCCESS.value, "success")
        self.assertEqual(DownloadStatus.FAILED.value, "failed")
        self.assertEqual(DownloadStatus.ABANDONED.value, "abandoned")


class TestRetryAction(unittest.TestCase):
    def test_values(self):
        self.assertEqual(RetryAction.RETRY.value, "retry")
        self.assertEqual(RetryAction.HAIL_MARY.value, "hail_mary")
        self.assertEqual(RetryAction.ABANDON.value, "abandon")
