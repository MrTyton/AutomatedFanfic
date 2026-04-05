"""Unit tests for HistoryRecorder and HistoryWriter."""

import multiprocessing
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from history.database import SyncHistoryDB
from history.models import (
    HistoryEventType,
    HistoryMessage,
)
from history.recorder import HistoryRecorder, HistoryWriter


class TestHistoryRecorder(unittest.TestCase):
    """Tests that HistoryRecorder puts correctly-structured messages on the queue."""

    def setUp(self):
        self.queue = multiprocessing.Queue()
        self.recorder = HistoryRecorder(self.queue)

    def tearDown(self):
        self.queue.close()
        self.queue.join_thread()

    def _get_msg(self) -> dict:
        return self.queue.get(timeout=2)

    def test_record_download_created(self):
        self.recorder.record_download_created(
            url="https://ao3.org/works/1", site="ao3", behavior="force"
        )
        raw = self._get_msg()
        msg = HistoryMessage(**raw)
        self.assertEqual(msg.event_type, HistoryEventType.DOWNLOAD_CREATED)
        self.assertEqual(msg.payload["url"], "https://ao3.org/works/1")
        self.assertEqual(msg.payload["site"], "ao3")
        self.assertEqual(msg.payload["behavior"], "force")

    def test_record_download_success(self):
        self.recorder.record_download_success(url="u", title="Story", calibre_id="42")
        raw = self._get_msg()
        msg = HistoryMessage(**raw)
        self.assertEqual(msg.event_type, HistoryEventType.DOWNLOAD_UPDATED)
        self.assertEqual(msg.payload["status"], "success")
        self.assertEqual(msg.payload["title"], "Story")
        self.assertEqual(msg.payload["calibre_id"], "42")

    def test_record_download_failed(self):
        self.recorder.record_download_failed(url="u", error_message="timeout")
        raw = self._get_msg()
        msg = HistoryMessage(**raw)
        self.assertEqual(msg.payload["status"], "failed")
        self.assertEqual(msg.payload["error_message"], "timeout")

    def test_record_download_abandoned(self):
        self.recorder.record_download_abandoned(url="u", error_message="done")
        raw = self._get_msg()
        msg = HistoryMessage(**raw)
        self.assertEqual(msg.payload["status"], "abandoned")

    def test_record_retry(self):
        self.recorder.record_retry(
            url="u",
            site="s",
            attempt_number=3,
            action="retry",
            delay_minutes=3.0,
            error_message="err",
        )
        raw = self._get_msg()
        msg = HistoryMessage(**raw)
        self.assertEqual(msg.event_type, HistoryEventType.RETRY)
        self.assertEqual(msg.payload["attempt_number"], 3)
        self.assertEqual(msg.payload["action"], "retry")
        self.assertEqual(msg.payload["delay_minutes"], 3.0)

    def test_record_retry_fired(self):
        self.recorder.record_retry_fired(url="u", attempt_number=5)
        raw = self._get_msg()
        msg = HistoryMessage(**raw)
        self.assertEqual(msg.event_type, HistoryEventType.RETRY_FIRED)
        self.assertEqual(msg.payload["attempt_number"], 5)
        self.assertIn("fired_at", msg.payload)

    def test_record_email_check(self):
        self.recorder.record_email_check(
            urls_found=10, urls_new=3, urls_duplicate=5, urls_disabled_site=2
        )
        raw = self._get_msg()
        msg = HistoryMessage(**raw)
        self.assertEqual(msg.event_type, HistoryEventType.EMAIL_CHECK)
        self.assertEqual(msg.payload["urls_found"], 10)
        self.assertEqual(msg.payload["urls_new"], 3)

    def test_record_notification(self):
        self.recorder.record_notification(
            title="New Download",
            body="Story X",
            site="ao3",
            provider="apprise",
        )
        raw = self._get_msg()
        msg = HistoryMessage(**raw)
        self.assertEqual(msg.event_type, HistoryEventType.NOTIFICATION)
        self.assertEqual(msg.payload["title"], "New Download")
        self.assertEqual(msg.payload["provider"], "apprise")

    def test_put_failure_does_not_raise(self):
        """Recording to a broken queue silently fails."""
        self.queue.close()
        self.queue.join_thread()
        # Should not raise
        self.recorder.record_download_created(url="u", site="s")


class TestHistoryWriter(unittest.TestCase):
    """Tests that HistoryWriter drains the queue and persists events."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.queue = multiprocessing.Queue()
        self.shutdown = threading.Event()
        self.writer = HistoryWriter(self.queue, self.tmp.name, self.shutdown)

    def tearDown(self):
        self.shutdown.set()
        self.writer.stop()
        self.queue.close()
        self.queue.join_thread()
        os.unlink(self.tmp.name)

    def _start_writer(self):
        self.writer.start()
        # Give the writer thread time to start and create tables
        time.sleep(0.3)

    def _verify_db(self) -> SyncHistoryDB:
        db = SyncHistoryDB(self.tmp.name)
        db.connect()
        return db

    def test_processes_download_created(self):
        self._start_writer()
        recorder = HistoryRecorder(self.queue)
        recorder.record_download_created(url="https://ao3.org/works/1", site="ao3")

        time.sleep(0.5)  # Let writer drain
        self.shutdown.set()
        self.writer.stop()

        db = self._verify_db()
        cur = db._conn.execute("SELECT url, site, status FROM download_events")
        row = cur.fetchone()
        db.close()
        self.assertEqual(row[0], "https://ao3.org/works/1")
        self.assertEqual(row[1], "ao3")
        self.assertEqual(row[2], "pending")

    def test_processes_download_update(self):
        self._start_writer()
        recorder = HistoryRecorder(self.queue)
        recorder.record_download_created(url="u", site="s")
        time.sleep(0.3)
        recorder.record_download_success(url="u", title="T", calibre_id="1")
        time.sleep(0.5)
        self.shutdown.set()
        self.writer.stop()

        db = self._verify_db()
        cur = db._conn.execute("SELECT status, title, calibre_id FROM download_events")
        row = cur.fetchone()
        db.close()
        self.assertEqual(row[0], "success")
        self.assertEqual(row[1], "T")

    def test_processes_retry(self):
        self._start_writer()
        recorder = HistoryRecorder(self.queue)
        recorder.record_retry(
            url="u",
            site="s",
            attempt_number=2,
            action="retry",
            delay_minutes=2.0,
        )
        time.sleep(0.5)
        self.shutdown.set()
        self.writer.stop()

        db = self._verify_db()
        cur = db._conn.execute(
            "SELECT attempt_number, action, delay_minutes FROM retry_events"
        )
        row = cur.fetchone()
        db.close()
        self.assertEqual(row[0], 2)
        self.assertEqual(row[1], "retry")
        self.assertEqual(row[2], 2.0)

    def test_processes_email_check(self):
        self._start_writer()
        recorder = HistoryRecorder(self.queue)
        recorder.record_email_check(urls_found=5, urls_new=2)
        time.sleep(0.5)
        self.shutdown.set()
        self.writer.stop()

        db = self._verify_db()
        cur = db._conn.execute("SELECT urls_found, urls_new FROM email_events")
        row = cur.fetchone()
        db.close()
        self.assertEqual(row[0], 5)
        self.assertEqual(row[1], 2)

    def test_processes_notification(self):
        self._start_writer()
        recorder = HistoryRecorder(self.queue)
        recorder.record_notification(title="t", body="b", provider="apprise")
        time.sleep(0.5)
        self.shutdown.set()
        self.writer.stop()

        db = self._verify_db()
        cur = db._conn.execute("SELECT title, body, provider FROM notification_events")
        row = cur.fetchone()
        db.close()
        self.assertEqual(row[0], "t")
        self.assertEqual(row[1], "b")
        self.assertEqual(row[2], "apprise")

    def test_drains_on_shutdown(self):
        """Messages queued before shutdown are still processed."""
        self._start_writer()
        recorder = HistoryRecorder(self.queue)

        for i in range(5):
            recorder.record_download_created(url=f"u{i}", site="s")

        time.sleep(0.5)
        self.shutdown.set()
        self.writer.stop()

        db = self._verify_db()
        cur = db._conn.execute("SELECT COUNT(*) FROM download_events")
        count = cur.fetchone()[0]
        db.close()
        self.assertEqual(count, 5)

    @patch("history.recorder.ff_logging")
    def test_malformed_message_logged_not_crashed(self, mock_logging):
        """Bad messages are logged and skipped, writer keeps running."""
        self._start_writer()

        # Put a malformed message
        self.queue.put({"event_type": "bogus", "payload": {}})
        # Then a valid one
        recorder = HistoryRecorder(self.queue)
        recorder.record_download_created(url="u", site="s")

        time.sleep(0.5)
        self.shutdown.set()
        self.writer.stop()

        db = self._verify_db()
        cur = db._conn.execute("SELECT COUNT(*) FROM download_events")
        count = cur.fetchone()[0]
        db.close()
        self.assertEqual(count, 1)

    def test_stop_without_start_is_safe(self):
        """Stopping a writer that was never started should not error."""
        writer = HistoryWriter(self.queue, self.tmp.name)
        writer.stop()
