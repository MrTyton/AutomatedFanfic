import multiprocessing as mp
from typing import NamedTuple
import unittest
from unittest.mock import patch, call


from parameterized import parameterized

import fanfic_info
import ff_waiter
import retry_types


class TestProcessFanfic(unittest.TestCase):
    """Test the process_fanfic function with pre-calculated retry decisions."""

    class ProcessFanficTestCase(NamedTuple):
        action: retry_types.FailureAction
        delay_minutes: float
        expected_delay_seconds: int
        expected_log_pattern: str
        description: str

    @parameterized.expand(
        [
            ProcessFanficTestCase(
                action=retry_types.FailureAction.RETRY,
                delay_minutes=5.0,
                expected_delay_seconds=300,
                expected_log_pattern="Waiting ~5.00 minutes for url in queue site (retry #2)",
                description="Regular retry with 5 minute delay",
            ),
            ProcessFanficTestCase(
                action=retry_types.FailureAction.RETRY,
                delay_minutes=10.5,
                expected_delay_seconds=630,
                expected_log_pattern="Waiting ~10.50 minutes for url in queue site (retry #2)",
                description="Regular retry with fractional delay",
            ),
            ProcessFanficTestCase(
                action=retry_types.FailureAction.HAIL_MARY,
                delay_minutes=720.0,
                expected_delay_seconds=43200,
                expected_log_pattern="Hail-Mary attempt: Waiting 720.0 minutes for url in queue site",
                description="Hail-Mary with 12 hour delay",
            ),
        ]
    )
    @patch("ff_waiter.ff_logging.log")
    @patch("threading.Timer")
    def test_process_fanfic_with_decisions(
        self,
        action,
        delay_minutes,
        expected_delay_seconds,
        expected_log_pattern,
        description,
        mock_timer,
        mock_log,
    ):
        """Test that process_fanfic correctly applies pre-calculated retry decisions."""
        # Create fanfic with retry decision
        fanfic = fanfic_info.FanficInfo(site="site", url="url", repeats=2)
        fanfic.retry_decision = retry_types.RetryDecision(
            action=action,
            delay_minutes=delay_minutes,
            should_notify=False,
            notification_message="",
        )

        ingress_queue = mp.Queue()

        ff_waiter.process_fanfic(fanfic, ingress_queue)

        # Verify the logging contains expected pattern
        mock_log.assert_called_once()
        log_call_args = mock_log.call_args[0]
        self.assertIn(expected_log_pattern, log_call_args[0])
        self.assertEqual("WARNING", log_call_args[1])

        # Verify the timer was called with the correct delay
        mock_timer.assert_called_once_with(
            expected_delay_seconds,
            ff_waiter.insert_after_time,
            args=(ingress_queue, fanfic),
        )
        mock_timer.return_value.start.assert_called_once()

    @patch("ff_waiter.ff_logging.log")
    @patch("threading.Timer")
    def test_process_fanfic_with_no_decision(self, mock_timer, mock_log):
        """Test that process_fanfic handles missing retry decision with fallback."""
        fanfic = fanfic_info.FanficInfo(site="site", url="url")
        # No retry_decision set (None)

        ingress_queue = mp.Queue()

        ff_waiter.process_fanfic(fanfic, ingress_queue)

        # Should log warning about missing decision and retry details
        self.assertEqual(mock_log.call_count, 2)
        first_log_call = mock_log.call_args_list[0]
        self.assertIn("No retry decision found for url", first_log_call[0][0])
        self.assertEqual("WARNING", first_log_call[0][1])

        # Should use default 5 minute delay
        mock_timer.assert_called_once_with(
            300, ff_waiter.insert_after_time, args=(ingress_queue, fanfic)
        )

    @patch("ff_waiter.ff_logging.log")
    def test_process_fanfic_abandon_action(self, mock_log):
        """Test that ABANDON action is handled correctly (should not schedule timer)."""
        fanfic = fanfic_info.FanficInfo(site="site", url="url")
        fanfic.retry_decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.ABANDON,
            delay_minutes=0.0,
            should_notify=False,
            notification_message="",
        )

        ingress_queue = mp.Queue()

        with patch("threading.Timer") as mock_timer:
            ff_waiter.process_fanfic(fanfic, ingress_queue)

            # Should log error and not start timer
            mock_log.assert_called_once()
            log_call_args = mock_log.call_args[0]
            self.assertIn(
                "Unexpected abandon action in waiting queue", log_call_args[0]
            )
            self.assertEqual("ERROR", log_call_args[1])

            # Timer should not be called
            mock_timer.assert_not_called()


class TestInsertAfterTime(unittest.TestCase):
    """Test the insert_after_time function."""

    def test_insert_after_time_queue_put(self):
        """Test that insert_after_time correctly puts fanfic into queue."""
        # Create a real queue to test actual functionality
        queue = mp.Queue()
        fanfic = fanfic_info.FanficInfo(site="test_site", url="test_url")

        # Call the function
        ff_waiter.insert_after_time(queue, fanfic)

        # Verify the fanfic was put in the queue
        retrieved_fanfic = queue.get(timeout=1)  # 1 second timeout
        self.assertEqual(retrieved_fanfic, fanfic)
        self.assertEqual(retrieved_fanfic.site, "test_site")
        self.assertEqual(retrieved_fanfic.url, "test_url")

    def test_insert_after_time_queue_empty_after_get(self):
        """Test that queue is empty after getting the item."""
        queue = mp.Queue()
        fanfic = fanfic_info.FanficInfo(site="another_site", url="another_url")

        ff_waiter.insert_after_time(queue, fanfic)

        # Get the item
        retrieved_fanfic = queue.get(timeout=1)
        self.assertEqual(retrieved_fanfic, fanfic)

        # Queue should now be empty
        self.assertTrue(queue.empty())


class TestWaitProcessor(unittest.TestCase):
    """Test the wait_processor function."""

    @patch("ff_waiter.process_fanfic")
    @patch("ff_waiter.sleep")
    def test_wait_processor_processes_fanfics(self, mock_sleep, mock_process_fanfic):
        """Test that wait_processor processes fanfics from the waiting queue."""
        waiting_queue = mp.Queue()
        ingress_queue = mp.Queue()

        # Add a fanfic and then poison pill to stop the loop
        fanfic = fanfic_info.FanficInfo(site="test_site", url="test_url")
        waiting_queue.put(fanfic)
        waiting_queue.put(None)  # Poison pill to stop processing

        # Run the processor
        ff_waiter.wait_processor(ingress_queue, waiting_queue)

        # Verify process_fanfic was called with the correct arguments
        mock_process_fanfic.assert_called_once_with(fanfic, ingress_queue)

        # Verify sleep was called
        mock_sleep.assert_called_with(5)

    @patch("ff_waiter.process_fanfic")
    @patch("ff_waiter.sleep")
    def test_wait_processor_poison_pill_shutdown(self, mock_sleep, mock_process_fanfic):
        """Test that wait_processor stops when receiving None (poison pill)."""
        waiting_queue = mp.Queue()
        ingress_queue = mp.Queue()

        # Add only poison pill - should stop immediately
        waiting_queue.put(None)

        # Run the processor
        ff_waiter.wait_processor(ingress_queue, waiting_queue)

        # Verify process_fanfic was never called
        mock_process_fanfic.assert_not_called()

        # Verify sleep was never called (no processing iteration)
        mock_sleep.assert_not_called()

    @patch("ff_waiter.process_fanfic")
    @patch("ff_waiter.sleep")
    def test_wait_processor_multiple_fanfics(self, mock_sleep, mock_process_fanfic):
        """Test that wait_processor handles multiple fanfics before shutdown."""
        waiting_queue = mp.Queue()
        ingress_queue = mp.Queue()

        # Add multiple fanfics and then poison pill
        fanfic1 = fanfic_info.FanficInfo(site="site1", url="url1")
        fanfic2 = fanfic_info.FanficInfo(site="site2", url="url2")
        fanfic3 = fanfic_info.FanficInfo(site="site1", url="url3")

        waiting_queue.put(fanfic1)
        waiting_queue.put(fanfic2)
        waiting_queue.put(fanfic3)
        waiting_queue.put(None)  # Poison pill

        # Run the processor
        ff_waiter.wait_processor(ingress_queue, waiting_queue)

        # Verify process_fanfic was called for each fanfic
        expected_calls = [
            call(fanfic1, ingress_queue),
            call(fanfic2, ingress_queue),
            call(fanfic3, ingress_queue),
        ]
        mock_process_fanfic.assert_has_calls(expected_calls)

        # Verify sleep was called 3 times (once per fanfic processed)
        self.assertEqual(mock_sleep.call_count, 3)
        mock_sleep.assert_has_calls([call(5), call(5), call(5)])


if __name__ == "__main__":
    unittest.main()
