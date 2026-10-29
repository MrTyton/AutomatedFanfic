import json
import os
import queue
import tempfile
import time
from typing import NamedTuple
import unittest
from unittest.mock import patch


from freezegun import freeze_time
from parameterized import parameterized

from utils import ff_logging


class TestLogFunction(unittest.TestCase):
    class CheckLogHeaderTestCase(NamedTuple):
        log_type: str
        message: str
        expected_header: str
        expected_color_code: str

    @parameterized.expand(
        [
            CheckLogHeaderTestCase(
                log_type="header",
                message="testing header",
                expected_header="HEADER",
                expected_color_code="95",
            ),
            CheckLogHeaderTestCase(
                log_type="okblue",
                message="testing okblue",
                expected_header="OKBLUE",
                expected_color_code="94",
            ),
            CheckLogHeaderTestCase(
                log_type="okgreen",
                message="testing okgreen",
                expected_header="OKGREEN",
                expected_color_code="92",
            ),
            CheckLogHeaderTestCase(
                log_type="warning",
                message="testing warning",
                expected_header="WARNING",
                expected_color_code="93",
            ),
            CheckLogHeaderTestCase(
                log_type="fail",
                message="testing fail",
                expected_header="FAIL",
                expected_color_code="91",
            ),
            CheckLogHeaderTestCase(
                log_type="endc",
                message="testing endc",
                expected_header="ENDC",
                expected_color_code="0",
            ),
            CheckLogHeaderTestCase(
                log_type="bold",
                message="testing bold",
                expected_header="BOLD",
                expected_color_code="1",
            ),
            CheckLogHeaderTestCase(
                log_type="underline",
                message="testing underline",
                expected_header="UNDERLINE",
                expected_color_code="4",
            ),
        ]
    )
    @freeze_time("2021-01-01 12:00:00")
    @patch("builtins.print")
    def test_log_header(self, name, message, color, code, mock_print):
        ff_logging.log(message, color)
        mock_print.assert_called_once_with(
            f"\x1b[1m2021-01-01 12:00:00 PM\x1b[0m - \x1b[{code}m{message}\x1b[0m",
            flush=True,
        )


class TestLogForwarding(unittest.TestCase):
    """Tests for cross-process log forwarding via set_log_forward_queue."""

    def setUp(self):
        # Always start each test with forwarding disabled and web_enabled True.
        ff_logging.set_web_enabled(True)
        ff_logging.set_log_forward_queue(None)
        if hasattr(ff_logging._thread_local, "color"):
            del ff_logging._thread_local.color
        with ff_logging._log_buffer_lock:
            ff_logging._log_buffer.clear()
            ff_logging._startup_log_buffer.clear()
            ff_logging._startup_capture_enabled = True

    def tearDown(self):
        # Restore clean state so other tests are not affected.
        ff_logging.set_web_enabled(True)
        ff_logging.set_log_forward_queue(None)
        if hasattr(ff_logging._thread_local, "color"):
            del ff_logging._thread_local.color
        with ff_logging._log_buffer_lock:
            ff_logging._startup_capture_enabled = True

    @patch("builtins.print")
    def test_log_puts_entry_to_forward_queue_when_set(self, _mock_print):
        """log() enqueues the entry when a forward queue is configured."""
        q: queue.Queue = queue.Queue()
        ff_logging.set_log_forward_queue(q)
        ff_logging.log("hello forward")
        self.assertFalse(q.empty(), "Expected an entry in the forward queue")
        entry = q.get_nowait()
        self.assertEqual(entry["message"], "hello forward")
        self.assertEqual(entry["level"], "info")
        self.assertNotIn("thread_color", entry)

    @patch("builtins.print")
    def test_log_includes_thread_color_when_set(self, _mock_print):
        """log() includes thread color metadata for worker differentiation."""
        q: queue.Queue = queue.Queue()
        ff_logging.set_log_forward_queue(q)
        ff_logging.set_thread_color("\033[38;5;210m")
        ff_logging.log("worker color entry")
        entry = q.get_nowait()
        self.assertEqual(entry["thread_color"], "\033[38;5;210m")

    @patch("builtins.print")
    def test_log_does_not_put_when_queue_is_none(self, _mock_print):
        """log() must not raise and must not push when no queue is set."""
        # _log_forward_queue is already None from setUp
        # This should simply not raise:
        ff_logging.log("no queue")

    @patch("builtins.print")
    def test_set_log_forward_queue_replays_buffered_logs(self, _mock_print):
        """set_log_forward_queue() replays logs emitted prior to queue attachment."""
        ff_logging.log("early startup banner")
        ff_logging.log("early tool versions")
        q: queue.Queue = queue.Queue()
        ff_logging.set_log_forward_queue(q)

        replayed = []
        while not q.empty():
            replayed.append(q.get_nowait()["message"])

        self.assertIn("early startup banner", replayed)
        self.assertIn("early tool versions", replayed)
        self.assertLess(
            replayed.index("early startup banner"),
            replayed.index("early tool versions"),
        )

    @patch("builtins.print")
    def test_log_failure_forwarded_with_error_level(self, _mock_print):
        """log_failure() entries forwarded with level='error'."""
        q: queue.Queue = queue.Queue()
        ff_logging.set_log_forward_queue(q)
        ff_logging.log_failure("something broke")
        entry = q.get_nowait()
        self.assertEqual(entry["level"], "error")
        self.assertEqual(entry["message"], "something broke")

    @patch("builtins.print")
    def test_log_ignores_full_or_broken_queue(self, _mock_print):
        """A queue that raises on put_nowait must not propagate the exception."""

        class _BrokenQueue(queue.Queue):
            def put_nowait(self, item):
                raise RuntimeError("queue is broken")

        ff_logging.set_log_forward_queue(_BrokenQueue())
        # Must not raise:
        ff_logging.log("should be silent")

    @patch("builtins.print")
    def test_start_log_drain_thread_populates_buffer(self, _mock_print):
        """start_log_drain_thread() must move queue entries into _log_buffer."""
        q: queue.Queue = queue.Queue()
        entry = {
            "timestamp": "2026-01-01 12:00:00 PM",
            "level": "info",
            "message": "drained",
        }
        q.put(entry)

        drain_thread = ff_logging.start_log_drain_thread(q)
        self.assertTrue(drain_thread.daemon)

        # Give the drain thread a moment to consume the entry.
        deadline = time.monotonic() + 2.0
        found = False
        while time.monotonic() < deadline:
            with ff_logging._log_buffer_lock:
                found = any(e["message"] == "drained" for e in ff_logging._log_buffer)
            if found:
                break
            time.sleep(0.05)

        self.assertTrue(found, "Drain thread did not populate _log_buffer in time")

    @patch("builtins.print")
    def test_startup_log_buffer_stops_after_startup_marker(self, _mock_print):
        """Startup buffer should freeze once startup-complete marker is logged."""
        ff_logging.log("before marker")
        ff_logging.log("All processes started successfully")
        ff_logging.log("after marker")

        startup_entries = ff_logging.get_startup_logs(limit=50)
        startup_messages = [entry["message"] for entry in startup_entries]

        self.assertIn("before marker", startup_messages)
        self.assertIn("All processes started successfully", startup_messages)
        self.assertNotIn("after marker", startup_messages)

    @patch("builtins.print")
    def test_log_debug_skipped_when_web_disabled_and_verbose_false(self, mock_print):
        """When web_enabled=False and verbose=False, log_debug does zero work and neither prints nor buffers."""
        ff_logging.set_verbose(False)
        ff_logging.set_web_enabled(False)
        q: queue.Queue = queue.Queue()
        ff_logging.set_log_forward_queue(q)

        ff_logging.log_debug("invisible debug log")

        mock_print.assert_not_called()
        self.assertTrue(q.empty())
        self.assertEqual(ff_logging.get_recent_logs(), [])

    @patch("builtins.print")
    def test_log_debug_forwarded_to_web_when_web_enabled_and_verbose_false(
        self, mock_print
    ):
        """When web_enabled=True and verbose=False, log_debug does not print to console but buffers and forwards to Web UI."""
        ff_logging.set_verbose(False)
        ff_logging.set_web_enabled(True)
        q: queue.Queue = queue.Queue()
        ff_logging.set_log_forward_queue(q)

        ff_logging.log_debug("web debug entry")

        mock_print.assert_not_called()
        self.assertFalse(q.empty())
        entry = q.get_nowait()
        self.assertEqual(entry["level"], "debug")
        self.assertEqual(entry["message"], "web debug entry")


class TestPersistentLogging(unittest.TestCase):
    """Tests for persistent rotating JSONL file logging and startup rehydration."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = os.path.join(self.temp_dir.name, "test_persistent.log")
        ff_logging.set_web_enabled(True)
        with ff_logging._log_buffer_lock:
            ff_logging._log_buffer.clear()
            ff_logging._startup_log_buffer.clear()

    def tearDown(self):
        ff_logging.close_persistent_logging()
        self.temp_dir.cleanup()
        with ff_logging._log_buffer_lock:
            ff_logging._log_buffer.clear()
            ff_logging._startup_log_buffer.clear()

    def test_init_persistent_logging_and_append(self):
        ff_logging.init_persistent_logging(self.log_path)
        ff_logging.log("test persistent message")
        with open(self.log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 1)
        data = json.loads(lines[0])
        self.assertEqual(data["message"], "test persistent message")

    def test_rehydration_on_startup(self):
        entries = [
            {
                "timestamp": "2026-10-28 10:00:00 AM",
                "level": "info",
                "message": "msg 1",
                "story_url": "http://example.com/1",
            },
            {
                "timestamp": "2026-10-28 10:01:00 AM",
                "level": "error",
                "message": "msg 2",
                "attempt_id": "attempt-1",
            },
            "corrupted non-json line\n",
        ]
        with open(self.log_path, "w", encoding="utf-8") as f:
            for e in entries:
                if isinstance(e, dict):
                    f.write(json.dumps(e) + "\n")
                else:
                    f.write(e)

        ff_logging.init_persistent_logging(self.log_path)
        recent = ff_logging.get_recent_logs(limit=10)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["message"], "msg 2")
        self.assertEqual(recent[0]["attempt_id"], "attempt-1")
        self.assertEqual(recent[1]["message"], "msg 1")
        self.assertEqual(recent[1]["story_url"], "http://example.com/1")

    def test_rehydration_filters_out_system_logs(self):
        entries = [
            {
                "timestamp": "2026-10-28 09:00:00 AM",
                "level": "info",
                "message": "Starting AutomatedFanfic v2.1.0...",
            },
            {
                "timestamp": "2026-10-28 09:01:00 AM",
                "level": "info",
                "message": "Supervisor: All processes started successfully",
            },
            {
                "timestamp": "2026-10-28 09:02:00 AM",
                "level": "info",
                "message": "(archiveofourown.org) Processing https://archiveofourown.org/works/12345",
            },
            {
                "timestamp": "2026-10-28 09:05:00 AM",
                "level": "info",
                "message": "Shutting down AutomatedFanfic...",
            },
        ]
        with open(self.log_path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        ff_logging.init_persistent_logging(self.log_path)
        recent = ff_logging.get_recent_logs(limit=10)
        # Only the story processing line should be rehydrated
        self.assertEqual(len(recent), 1)
        self.assertEqual(
            recent[0]["message"],
            "(archiveofourown.org) Processing https://archiveofourown.org/works/12345",
        )


if __name__ == "__main__":
    unittest.main()
