"""Unit tests for SyncHistoryDB and AsyncHistoryDB."""

import asyncio
import os
import tempfile
import unittest
from datetime import datetime

from history.database import AsyncHistoryDB, SyncHistoryDB
from history.models import (
    DownloadEvent,
    DownloadStatus,
    EmailCheckEvent,
    NotificationEvent,
    RetryAction,
    RetryEvent,
)


class TestSyncHistoryDB(unittest.TestCase):
    """Tests for the synchronous SQLite writer used by HistoryWriter."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = SyncHistoryDB(self.tmp.name)
        self.db.connect()

    def tearDown(self):
        self.db.close()
        os.unlink(self.tmp.name)

    # -- download_events --

    def test_insert_download_returns_id(self):
        event = DownloadEvent(url="https://ao3.org/works/1", site="ao3")
        row_id = self.db.insert_download(event)
        self.assertIsInstance(row_id, int)
        self.assertGreater(row_id, 0)

    def test_insert_and_update_download_success(self):
        event = DownloadEvent(url="https://ao3.org/works/1", site="ao3")
        self.db.insert_download(event)

        now = datetime(2026, 1, 1, 12, 0, 0)
        self.db.update_download(
            url="https://ao3.org/works/1",
            status=DownloadStatus.SUCCESS,
            title="My Story",
            calibre_id="42",
            completed_at=now,
        )

        # Verify via raw SQL
        cur = self.db._conn.execute(
            "SELECT status, title, calibre_id, completed_at FROM download_events WHERE url = ?",
            ("https://ao3.org/works/1",),
        )
        row = cur.fetchone()
        self.assertEqual(row[0], "success")
        self.assertEqual(row[1], "My Story")
        self.assertEqual(row[2], "42")
        self.assertIn("2026-01-01", row[3])

    def test_update_download_abandoned(self):
        event = DownloadEvent(url="https://ffnet.com/s/1", site="ffnet")
        self.db.insert_download(event)

        self.db.update_download(
            url="https://ffnet.com/s/1",
            status=DownloadStatus.ABANDONED,
            error_message="Max retries exceeded",
        )

        cur = self.db._conn.execute(
            "SELECT status, error_message FROM download_events WHERE url = ?",
            ("https://ffnet.com/s/1",),
        )
        row = cur.fetchone()
        self.assertEqual(row[0], "abandoned")
        self.assertEqual(row[1], "Max retries exceeded")

    def test_update_targets_most_recent_pending(self):
        """If multiple downloads exist for same URL, update the latest pending one."""
        self.db.insert_download(
            DownloadEvent(
                url="u",
                site="s",
                status=DownloadStatus.SUCCESS,
                started_at=datetime(2026, 1, 1),
            )
        )
        self.db.insert_download(
            DownloadEvent(
                url="u",
                site="s",
                status=DownloadStatus.PENDING,
                started_at=datetime(2026, 1, 2),
            )
        )

        self.db.update_download(url="u", status=DownloadStatus.SUCCESS)

        cur = self.db._conn.execute(
            "SELECT status FROM download_events WHERE url = ? ORDER BY started_at",
            ("u",),
        )
        rows = cur.fetchall()
        self.assertEqual(rows[0][0], "success")  # first was already success
        self.assertEqual(rows[1][0], "success")  # second updated to success

    # -- retry_events --

    def test_insert_retry_links_to_download(self):
        dl_id = self.db.insert_download(
            DownloadEvent(url="https://ao3.org/works/1", site="ao3")
        )
        retry = RetryEvent(
            url="https://ao3.org/works/1",
            site="ao3",
            attempt_number=1,
            action=RetryAction.RETRY,
            delay_minutes=1.0,
        )
        retry_id = self.db.insert_retry(retry)
        self.assertGreater(retry_id, 0)

        # Verify FK linkage
        cur = self.db._conn.execute(
            "SELECT download_event_id FROM retry_events WHERE id = ?", (retry_id,)
        )
        self.assertEqual(cur.fetchone()[0], dl_id)

    def test_insert_retry_without_download(self):
        """Retry for unknown URL still inserts (download_event_id = NULL)."""
        retry = RetryEvent(
            url="https://unknown.com/1",
            site="unknown",
            attempt_number=5,
            action=RetryAction.HAIL_MARY,
            delay_minutes=720.0,
        )
        retry_id = self.db.insert_retry(retry)
        self.assertGreater(retry_id, 0)

    def test_update_retry_fired(self):
        retry = RetryEvent(
            url="https://ao3.org/works/1",
            site="ao3",
            attempt_number=2,
            action=RetryAction.RETRY,
        )
        self.db.insert_retry(retry)

        fired = datetime(2026, 1, 1, 13, 0, 0)
        self.db.update_retry_fired("https://ao3.org/works/1", 2, fired)

        cur = self.db._conn.execute(
            "SELECT fired_at FROM retry_events WHERE url = ? AND attempt_number = ?",
            ("https://ao3.org/works/1", 2),
        )
        self.assertIn("2026-01-01", cur.fetchone()[0])

    # -- email_events --

    def test_insert_email_check(self):
        event = EmailCheckEvent(
            urls_found=10, urls_new=3, urls_duplicate=5, urls_disabled_site=2
        )
        row_id = self.db.insert_email_check(event)
        self.assertGreater(row_id, 0)

        cur = self.db._conn.execute(
            "SELECT urls_found, urls_new, urls_duplicate, urls_disabled_site FROM email_events"
        )
        row = cur.fetchone()
        self.assertEqual(row, (10, 3, 5, 2))

    # -- notification_events --

    def test_insert_notification(self):
        event = NotificationEvent(
            title="New Download", body="Story X", site="ao3", provider="apprise"
        )
        row_id = self.db.insert_notification(event)
        self.assertGreater(row_id, 0)

    def test_insert_notification_links_to_download(self):
        self.db.insert_download(
            DownloadEvent(url="https://ao3.org/works/1", site="ao3")
        )
        event = NotificationEvent(
            title="t", body="b", site="ao3", provider="pushbullet"
        )
        self.db.insert_notification(event)

        cur = self.db._conn.execute("SELECT download_event_id FROM notification_events")
        row = cur.fetchone()
        self.assertIsNotNone(row[0])

    # -- schema idempotency --

    def test_connect_twice_is_safe(self):
        """Calling connect again doesn't error (CREATE IF NOT EXISTS)."""
        self.db.close()
        self.db.connect()


class TestAsyncHistoryDB(unittest.TestCase):
    """Tests for the async reader used by the FastAPI web server."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.async_db = AsyncHistoryDB(self.tmp.name)
        # Pre-populate via sync writer
        self.sync_db = SyncHistoryDB(self.tmp.name)
        self.sync_db.connect()

    def tearDown(self):
        self.sync_db.close()
        os.unlink(self.tmp.name)

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_get_downloads_empty(self):
        results = self._run(self.async_db.get_downloads())
        self.assertEqual(results, [])

    def test_get_downloads_returns_inserted(self):
        self.sync_db.insert_download(
            DownloadEvent(url="https://ao3.org/works/1", site="ao3", title="Story A")
        )
        self.sync_db.insert_download(
            DownloadEvent(url="https://ffnet.com/s/2", site="ffnet", title="Story B")
        )

        results = self._run(self.async_db.get_downloads())
        self.assertEqual(len(results), 2)
        # Most recent first
        urls = [r["url"] for r in results]
        self.assertIn("https://ao3.org/works/1", urls)
        self.assertIn("https://ffnet.com/s/2", urls)

    def test_get_downloads_filter_by_site(self):
        self.sync_db.insert_download(DownloadEvent(url="u1", site="ao3"))
        self.sync_db.insert_download(DownloadEvent(url="u2", site="ffnet"))

        results = self._run(self.async_db.get_downloads(site="ao3"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["site"], "ao3")

    def test_get_downloads_filter_by_status(self):
        self.sync_db.insert_download(DownloadEvent(url="u1", site="s"))
        self.sync_db.insert_download(DownloadEvent(url="u2", site="s"))
        self.sync_db.update_download(url="u1", status=DownloadStatus.SUCCESS)

        results = self._run(self.async_db.get_downloads(status="success"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "success")

    def test_get_download_count(self):
        self.sync_db.insert_download(DownloadEvent(url="u1", site="s"))
        self.sync_db.insert_download(DownloadEvent(url="u2", site="s"))

        count = self._run(self.async_db.get_download_count())
        self.assertEqual(count, 2)

    def test_get_download_count_filtered(self):
        self.sync_db.insert_download(DownloadEvent(url="u1", site="ao3"))
        self.sync_db.insert_download(DownloadEvent(url="u2", site="ffnet"))

        count = self._run(self.async_db.get_download_count(site="ao3"))
        self.assertEqual(count, 1)

    def test_get_retries_for_url(self):
        self.sync_db.insert_retry(
            RetryEvent(url="u1", site="s", attempt_number=1, action=RetryAction.RETRY)
        )
        self.sync_db.insert_retry(
            RetryEvent(url="u1", site="s", attempt_number=2, action=RetryAction.RETRY)
        )
        self.sync_db.insert_retry(
            RetryEvent(url="u2", site="s", attempt_number=1, action=RetryAction.RETRY)
        )

        results = self._run(self.async_db.get_retries_for_url("u1"))
        self.assertEqual(len(results), 2)

    def test_get_email_checks(self):
        self.sync_db.insert_email_check(EmailCheckEvent(urls_found=5, urls_new=3))
        results = self._run(self.async_db.get_email_checks())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["urls_found"], 5)

    def test_get_notifications(self):
        self.sync_db.insert_notification(
            NotificationEvent(title="t", body="b", provider="apprise")
        )
        results = self._run(self.async_db.get_notifications())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "t")

    def test_get_recent_events_mixed(self):
        self.sync_db.insert_download(DownloadEvent(url="u1", site="s"))
        self.sync_db.insert_retry(
            RetryEvent(url="u1", site="s", attempt_number=1, action=RetryAction.RETRY)
        )
        self.sync_db.insert_email_check(EmailCheckEvent(urls_found=1))

        results = self._run(self.async_db.get_recent_events(limit=10))
        event_types = {r["event_type"] for r in results}
        self.assertIn("download", event_types)
        self.assertIn("retry", event_types)
        self.assertIn("email_check", event_types)

    def test_pagination(self):
        for i in range(10):
            self.sync_db.insert_download(DownloadEvent(url=f"u{i}", site="s"))

        page1 = self._run(self.async_db.get_downloads(limit=3, offset=0))
        page2 = self._run(self.async_db.get_downloads(limit=3, offset=3))
        self.assertEqual(len(page1), 3)
        self.assertEqual(len(page2), 3)
        # No overlap
        ids1 = {r["id"] for r in page1}
        ids2 = {r["id"] for r in page2}
        self.assertEqual(len(ids1 & ids2), 0)

    def test_ensure_schema_idempotent(self):
        self._run(self.async_db.ensure_schema())
        self._run(self.async_db.ensure_schema())
