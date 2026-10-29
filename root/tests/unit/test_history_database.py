"""Unit tests for SyncHistoryDB and AsyncHistoryDB."""

import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone

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
        cur = self.db.conn.execute(
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

        cur = self.db.conn.execute(
            "SELECT status, error_message FROM download_events WHERE url = ?",
            ("https://ffnet.com/s/1",),
        )
        row = cur.fetchone()
        self.assertEqual(row[0], "abandoned")
        self.assertEqual(row[1], "Max retries exceeded")

    def test_success_update_clears_prior_error_message(self):
        """A success update must clear any error_message set by a prior failure."""
        event = DownloadEvent(url="https://ao3.org/works/99", site="ao3")
        self.db.insert_download(event)
        # Simulate a retry setting an error on the waiting row
        self.db.update_download(
            url="https://ao3.org/works/99",
            status=DownloadStatus.WAITING,
            error_message="FanFicFare reported a permanent failure condition.",
        )
        # Now the download succeeds
        self.db.update_download(
            url="https://ao3.org/works/99",
            status=DownloadStatus.SUCCESS,
            title="Epic Story",
        )

        cur = self.db.conn.execute(
            "SELECT status, error_message FROM download_events WHERE url = ?",
            ("https://ao3.org/works/99",),
        )
        row = cur.fetchone()
        self.assertEqual(row[0], "success")
        self.assertIsNone(
            row[1], "error_message should be NULL after a successful update"
        )

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

        cur = self.db.conn.execute(
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
        cur = self.db.conn.execute(
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

        cur = self.db.conn.execute(
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

        cur = self.db.conn.execute(
            "SELECT urls_found, urls_new, urls_duplicate, urls_disabled_site, trigger FROM email_events"
        )
        row = cur.fetchone()
        self.assertEqual(row, (10, 3, 5, 2, "poll"))

    def test_insert_email_check_idle_trigger(self):
        event = EmailCheckEvent(urls_found=2, urls_new=2, trigger="idle")
        self.db.insert_email_check(event)

        cur = self.db.conn.execute("SELECT trigger FROM email_events")
        row = cur.fetchone()
        self.assertEqual(row[0], "idle")

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

        cur = self.db.conn.execute("SELECT download_event_id FROM notification_events")
        row = cur.fetchone()
        self.assertIsNotNone(row[0])

    # -- schema idempotency --

    def test_connect_twice_is_safe(self):
        """Calling connect again doesn't error (CREATE IF NOT EXISTS)."""
        self.db.close()
        self.db.connect()

    def test_sync_db_synchronous_pragma(self):
        """PRAGMA synchronous should be NORMAL (1)."""
        row = self.db.conn.execute("PRAGMA synchronous").fetchone()
        assert row is not None
        self.assertEqual(row[0], 1)  # 0=OFF, 1=NORMAL, 2=FULL

    def test_sync_db_cache_size_pragma(self):
        """PRAGMA cache_size should be -65536 (64 MB)."""
        row = self.db.conn.execute("PRAGMA cache_size").fetchone()
        assert row is not None
        self.assertEqual(row[0], -65536)


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

    def test_get_recent_downloads_deduplicates_by_url_and_orders_by_latest_completion(
        self,
    ):
        """get_recent_downloads should deduplicate by URL and return the latest status."""
        self.sync_db.insert_download(
            DownloadEvent(
                url="https://ao3.org/works/1",
                site="ao3",
                title="Story A",
                status=DownloadStatus.SUCCESS,
                started_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
                completed_at=datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc),
            )
        )
        self.sync_db.insert_download(
            DownloadEvent(
                url="https://ao3.org/works/1",
                site="ao3",
                title="Story A",
                status=DownloadStatus.ABANDONED,
                started_at=datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc),
                completed_at=datetime(2026, 1, 2, 10, 1, tzinfo=timezone.utc),
            )
        )
        self.sync_db.insert_download(
            DownloadEvent(
                url="https://ao3.org/works/2",
                site="ao3",
                title="Story B",
                status=DownloadStatus.SUCCESS,
                started_at=datetime(2026, 1, 3, 10, 0, tzinfo=timezone.utc),
                completed_at=datetime(2026, 1, 3, 10, 5, tzinfo=timezone.utc),
            )
        )

        results = self._run(self.async_db.get_recent_downloads(limit=10))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["url"], "https://ao3.org/works/2")
        self.assertEqual(results[0]["status"], "success")
        self.assertEqual(results[1]["url"], "https://ao3.org/works/1")
        self.assertEqual(results[1]["status"], "abandoned")

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

    def test_get_waiting_urls_includes_error_message(self):
        self.sync_db.insert_download(DownloadEvent(url="u1", site="s"))
        self.sync_db.update_download(
            url="u1",
            status=DownloadStatus.WAITING,
            error_message="calibredb stderr",
        )

        results = self._run(self.async_db.get_waiting_urls())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "u1")
        self.assertEqual(results[0]["error_message"], "calibredb stderr")

    def test_get_waiting_urls_uses_latest_waiting_row_per_url(self):
        self.sync_db.insert_download(
            DownloadEvent(
                url="u1",
                site="s",
                status=DownloadStatus.WAITING,
                started_at=datetime(2026, 1, 1, 8, 0, 0),
                title="Old Title",
                error_message="old failure",
            )
        )
        self.sync_db.insert_download(
            DownloadEvent(
                url="u1",
                site="s",
                status=DownloadStatus.WAITING,
                started_at=datetime(2026, 1, 1, 9, 0, 0),
                title="New Title",
                error_message="new failure",
            )
        )

        results = self._run(self.async_db.get_waiting_urls())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "New Title")
        self.assertEqual(results[0]["error_message"], "new failure")

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

    def test_get_retries_includes_title(self):
        self.sync_db.insert_download(
            DownloadEvent(url="u1", site="ao3", title="Story One")
        )
        self.sync_db.insert_retry(
            RetryEvent(url="u1", site="ao3", attempt_number=1, action=RetryAction.RETRY)
        )

        results = self._run(self.async_db.get_retries(limit=10, offset=0))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Story One")

    def test_get_waiting_urls_includes_title_and_site(self):
        self.sync_db.insert_download(
            DownloadEvent(
                url="u1",
                site="ao3",
                title="Story One",
                calibre_id="42",
                status=DownloadStatus.WAITING,
            )
        )

        results = self._run(self.async_db.get_waiting_urls())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "u1")
        self.assertEqual(results[0]["site"], "ao3")
        self.assertEqual(results[0]["title"], "Story One")
        self.assertEqual(results[0]["calibre_id"], "42")

    def test_get_latest_download_returns_most_recent_row(self):
        self.sync_db.insert_download(
            DownloadEvent(url="u1", site="ao3", title="Old Title")
        )
        self.sync_db.insert_download(
            DownloadEvent(url="u1", site="ao3", title="New Title")
        )

        result = self._run(self.async_db.get_latest_download("u1"))
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["title"], "New Title")

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

    def test_async_db_synchronous_pragma(self):
        """PRAGMA synchronous should be NORMAL for async connection."""

        async def _inner():
            conn = await self.async_db._get_conn()
            try:
                async with conn.execute("PRAGMA synchronous") as cur:
                    row = await cur.fetchone()
                assert row is not None
                return row[0]
            finally:
                await conn.close()

        result = self._run(_inner())
        self.assertEqual(result, 1)  # 0=OFF, 1=NORMAL, 2=FULL

    def test_async_db_cache_size_pragma(self):
        """PRAGMA cache_size should be -65536 for async connection."""

        async def _inner():
            conn = await self.async_db._get_conn()
            try:
                async with conn.execute("PRAGMA cache_size") as cur:
                    row = await cur.fetchone()
                assert row is not None
                return row[0]
            finally:
                await conn.close()

        result = self._run(_inner())
        self.assertEqual(result, -65536)

    def test_persistent_connection_lifecycle_and_get_stats(self):
        """AsyncHistoryDB.connect() reuses a persistent connection across queries and get_stats() returns consolidated counts."""
        self.sync_db.insert_download(
            DownloadEvent(
                url="https://ao3.org/works/1",
                site="ao3",
                title="Story 1",
                status=DownloadStatus.SUCCESS,
            )
        )
        self.sync_db.insert_download(
            DownloadEvent(
                url="https://ao3.org/works/2",
                site="ao3",
                title="Story 2",
                status=DownloadStatus.FAILED,
                error_message="Connection timeout",
            )
        )
        self.sync_db.insert_retry(
            RetryEvent(
                url="https://ao3.org/works/2",
                site="ao3",
                attempt_number=1,
                action=RetryAction.HAIL_MARY,
            )
        )
        self.sync_db.insert_email_check(
            EmailCheckEvent(urls_found=4, urls_new=2, urls_duplicate=1)
        )
        self.sync_db.insert_notification(
            NotificationEvent(title="Done", body="Body", site="ao3")
        )

        async def _inner():
            await self.async_db.connect()
            try:
                self.assertIsNotNone(self.async_db._conn)
                stats = await self.async_db.get_stats()
                return stats
            finally:
                await self.async_db.close()
                self.assertIsNone(self.async_db._conn)

        stats = self._run(_inner())
        self.assertEqual(stats["total_downloads"], 2)
        self.assertEqual(stats["total_success"], 1)
        self.assertEqual(stats["total_failed"], 1)
        self.assertEqual(stats["total_retries"], 1)
        self.assertEqual(stats["period_downloads"], 2)
        self.assertEqual(stats["period_success"], 1)
        self.assertEqual(stats["period_failed"], 1)

    def test_get_downloads_case_insensitive_site(self):
        self.sync_db.insert_download(DownloadEvent(url="u1", site="RoyalRoad"))
        self.sync_db.insert_download(DownloadEvent(url="u2", site="spacebattles"))

        results = self._run(self.async_db.get_downloads(site="royalroad"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "u1")

    def test_get_distinct_sites(self):
        self.sync_db.insert_download(DownloadEvent(url="u1", site="RoyalRoad"))
        self.sync_db.insert_download(DownloadEvent(url="u2", site="spacebattles"))
        self.sync_db.insert_notification(
            NotificationEvent(title="T", body="B", site="ao3")
        )

        sites = self._run(self.async_db.get_distinct_sites())
        self.assertIn("RoyalRoad", sites)
        self.assertIn("spacebattles", sites)
        self.assertIn("ao3", sites)

    def test_prune_email_events_caps_table(self):
        for i in range(15):
            self.sync_db.insert_email_check(
                EmailCheckEvent(urls_found=i, urls_new=i, trigger="idle"),
                commit=True,
            )
        count_before = self._run(self.async_db.get_email_checks_count())
        self.assertEqual(count_before, 15)

        deleted = self.sync_db.prune_email_events(max_records=5)
        self.assertEqual(deleted, 10)
        count_after = self._run(self.async_db.get_email_checks_count())
        self.assertEqual(count_after, 5)

    def test_get_notifications_with_site_and_search_filter(self):
        self.sync_db.insert_notification(
            NotificationEvent(
                title="Chapter 1", body="Update available", site="RoyalRoad"
            )
        )
        self.sync_db.insert_notification(
            NotificationEvent(title="Chapter 2", body="Error downloading", site="AO3")
        )

        res_site = self._run(self.async_db.get_notifications(site="royalroad"))
        self.assertEqual(len(res_site), 1)
        self.assertEqual(res_site[0]["site"], "RoyalRoad")

        res_search = self._run(self.async_db.get_notifications(search="error"))
        self.assertEqual(len(res_search), 1)
        self.assertEqual(res_search[0]["site"], "AO3")
