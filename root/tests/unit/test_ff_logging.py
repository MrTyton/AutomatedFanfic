from typing import NamedTuple
import queue
import time
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
        # Always start each test with forwarding disabled.
        ff_logging.set_log_forward_queue(None)

    def tearDown(self):
        # Restore clean state so other tests are not affected.
        ff_logging.set_log_forward_queue(None)

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

    @patch("builtins.print")
    def test_log_does_not_put_when_queue_is_none(self, _mock_print):
        """log() must not raise and must not push when no queue is set."""
        # _log_forward_queue is already None from setUp
        # This should simply not raise:
        ff_logging.log("no queue")

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

        class _BrokenQueue:
            def put_nowait(self, item):
                raise RuntimeError("queue is broken")

        ff_logging.set_log_forward_queue(_BrokenQueue())
        # Must not raise:
        ff_logging.log("should be silent")

    @patch("builtins.print")
    def test_start_log_drain_thread_populates_buffer(self, _mock_print):
        """start_log_drain_thread() must move queue entries into _log_buffer."""
        q: queue.Queue = queue.Queue()
        entry = {"timestamp": "2026-01-01 12:00:00 PM", "level": "info", "message": "drained"}
        q.put(entry)

        drain_thread = ff_logging.start_log_drain_thread(q)
        self.assertTrue(drain_thread.daemon)

        # Give the drain thread a moment to consume the entry.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with ff_logging._log_buffer_lock:
                found = any(e["message"] == "drained" for e in ff_logging._log_buffer)
            if found:
                break
            time.sleep(0.05)

        self.assertTrue(found, "Drain thread did not populate _log_buffer in time")


if __name__ == "__main__":
    unittest.main()
