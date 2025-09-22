import multiprocessing as mp
from typing import NamedTuple
import unittest
from unittest.mock import patch, Mock, call


from freezegun import freeze_time
from parameterized import parameterized

import fanfic_info
import ff_waiter


class TestWaitFunction(unittest.TestCase):
    class CheckTimerProcessingTestCase(NamedTuple):
        repeats: int
        expected_base_delay: int
        jitter_multiplier: float
        expected_final_delay: int
        expected_log_message: str

    @parameterized.expand(
        [
            # Test case: retry_count=0, jitter=1.0 (no jitter)
            CheckTimerProcessingTestCase(
                repeats=0,
                expected_base_delay=0,
                jitter_multiplier=1.0,
                expected_final_delay=0,
                expected_log_message="Waiting ~0.00 minutes for url in queue site (retry #1, base: 0min, jitter: 1.00x)",
            ),
            # Test case: retry_count=1, jitter=1.0
            CheckTimerProcessingTestCase(
                repeats=1,
                expected_base_delay=60,
                jitter_multiplier=1.0,
                expected_final_delay=60,
                expected_log_message="Waiting ~1.00 minutes for url in queue site (retry #2, base: 1min, jitter: 1.00x)",
            ),
            # Test case: retry_count=5, jitter=0.5 (minimum jitter)
            CheckTimerProcessingTestCase(
                repeats=5,
                expected_base_delay=300,
                jitter_multiplier=0.5,
                expected_final_delay=150,
                expected_log_message="Waiting ~2.50 minutes for url in queue site (retry #6, base: 5min, jitter: 0.50x)",
            ),
            # Test case: retry_count=10, jitter=1.5 (maximum jitter)
            CheckTimerProcessingTestCase(
                repeats=10,
                expected_base_delay=600,
                jitter_multiplier=1.5,
                expected_final_delay=900,
                expected_log_message="Waiting ~15.00 minutes for url in queue site (retry #11, base: 10min, jitter: 1.50x)",
            ),
            # Test case: retry_count=25, should be capped at 20 minutes (1200 seconds)
            CheckTimerProcessingTestCase(
                repeats=25,
                expected_base_delay=1200,
                jitter_multiplier=1.0,
                expected_final_delay=1200,
                expected_log_message="Waiting ~20.00 minutes for url in queue site (retry #26, base: 20min, jitter: 1.00x)",
            ),
        ]
    )
    @freeze_time("2021-01-01 12:00:00")
    @patch("ff_waiter.ff_logging.log")
    @patch("threading.Timer")
    @patch("random.uniform")
    def test_wait_with_jitter(
        self,
        repeats,
        expected_base_delay,
        jitter_multiplier,
        expected_final_delay,
        expected_log_message,
        mock_random,
        mock_timer,
        mock_log,
    ):
        # Mock the random jitter to return a predictable value
        mock_random.return_value = jitter_multiplier

        fanfic = fanfic_info.FanficInfo(site="site", url="url", repeats=repeats)
        queue = mp.Queue()
        processor_queues = {"site": queue}

        ff_waiter.process_fanfic(fanfic, processor_queues)

        # Verify the logging was called with the expected message
        mock_log.assert_called_once_with(expected_log_message, "WARNING")

        # Verify the timer was called with the correct delay
        mock_timer.assert_called_once_with(
            expected_final_delay, ff_waiter.insert_after_time, args=(queue, fanfic)
        )
        mock_timer.return_value.start.assert_called_once()

        # Verify random.uniform was called with correct range (0.5, 1.5)
        mock_random.assert_called_once_with(0.5, 1.5)


class TestDelayCalculation(unittest.TestCase):
    """Test the delay calculation logic separately for better coverage."""

    class DelayCalculationTestCase(NamedTuple):
        retry_count: int
        expected_base_delay: int
        description: str

    @parameterized.expand(
        [
            DelayCalculationTestCase(0, 0, "No retries should have 0 delay"),
            DelayCalculationTestCase(1, 60, "First retry should be 1 minute"),
            DelayCalculationTestCase(5, 300, "Fifth retry should be 5 minutes"),
            DelayCalculationTestCase(10, 600, "Tenth retry should be 10 minutes"),
            DelayCalculationTestCase(15, 900, "Fifteenth retry should be 15 minutes"),
            DelayCalculationTestCase(
                20, 1200, "Twentieth retry should be capped at 20 minutes"
            ),
            DelayCalculationTestCase(
                30, 1200, "Retry beyond 20 should still be capped at 20 minutes"
            ),
            DelayCalculationTestCase(
                100, 1200, "Very high retry count should still be capped"
            ),
        ]
    )
    @patch("random.uniform")
    def test_base_delay_calculation(
        self, retry_count, expected_base_delay, description, mock_random
    ):
        """Test that base delay calculation follows the expected linear progression with cap."""
        # Set jitter to 1.0 to isolate base delay testing
        mock_random.return_value = 1.0

        fanfic = fanfic_info.FanficInfo(
            site="test_site", url="test_url", repeats=retry_count
        )

        with patch("threading.Timer") as mock_timer, patch(
            "ff_waiter.ff_logging.log"
        ) as mock_log:

            ff_waiter.process_fanfic(fanfic, {"test_site": mp.Queue()})

            # Verify the timer was called with the expected base delay
            mock_timer.assert_called_once()
            actual_delay = mock_timer.call_args[0][0]  # First argument to Timer()
            self.assertEqual(actual_delay, expected_base_delay, description)


class TestJitterRange(unittest.TestCase):
    """Test that jitter is applied correctly within the expected range."""

    class JitterRangeTestCase(NamedTuple):
        jitter: float
        expected_delay: int
        description: str

    @parameterized.expand(
        [
            JitterRangeTestCase(
                jitter=0.5,
                expected_delay=300,
                description="Minimum jitter (0.5) should produce minimum delay",
            ),
            JitterRangeTestCase(
                jitter=0.75,
                expected_delay=450,
                description="Mid-low jitter (0.75) should produce proportional delay",
            ),
            JitterRangeTestCase(
                jitter=1.0,
                expected_delay=600,
                description="No jitter (1.0) should produce base delay",
            ),
            JitterRangeTestCase(
                jitter=1.25,
                expected_delay=750,
                description="Mid-high jitter (1.25) should produce proportional delay",
            ),
            JitterRangeTestCase(
                jitter=1.5,
                expected_delay=900,
                description="Maximum jitter (1.5) should produce maximum delay",
            ),
        ]
    )
    @patch("threading.Timer")
    @patch("ff_waiter.ff_logging.log")
    @patch("random.uniform")
    def test_jitter_range(
        self, jitter, expected_delay, description, mock_random, mock_log, mock_timer
    ):
        """Test that jitter produces delays within the expected range."""
        fanfic = fanfic_info.FanficInfo(
            site="site", url="url", repeats=10
        )  # 10 minute base
        queue = mp.Queue()
        processor_queues = {"site": queue}

        mock_random.return_value = jitter

        ff_waiter.process_fanfic(fanfic, processor_queues)

        # Extract the delay that was passed to Timer
        delay = mock_timer.call_args[0][0]

        # Base delay is 600 seconds (10 minutes)
        # Expected delay = 600 * jitter
        self.assertEqual(
            delay,
            expected_delay,
            f"Delay {delay} doesn't match expected {expected_delay} for jitter {jitter}: {description}",
        )

        # Verify the delay is within overall bounds
        # With jitter 0.5-1.5, final delay should be 300-900 seconds
        self.assertGreaterEqual(
            delay, 300, f"Delay {delay} is below minimum expected (300s): {description}"
        )
        self.assertLessEqual(
            delay, 900, f"Delay {delay} is above maximum expected (900s): {description}"
        )


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions."""

    @patch("threading.Timer")
    @patch("ff_waiter.ff_logging.log")
    @patch("random.uniform")
    def test_none_repeats(self, mock_random, mock_log, mock_timer):
        """Test that None repeats is handled correctly (defaults to 0)."""
        mock_random.return_value = 1.0

        fanfic = fanfic_info.FanficInfo(site="site", url="url", repeats=None)
        queue = mp.Queue()
        processor_queues = {"site": queue}

        ff_waiter.process_fanfic(fanfic, processor_queues)

        # Should be treated as retry_count=0, so base_delay=0
        mock_timer.assert_called_once_with(
            0, ff_waiter.insert_after_time, args=(queue, fanfic)
        )

        # Log should show retry #1 (retry_count + 1)
        expected_log = "Waiting ~0.00 minutes for url in queue site (retry #1, base: 0min, jitter: 1.00x)"
        mock_log.assert_called_once_with(expected_log, "WARNING")


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
        processor_queues = {"test_site": mp.Queue()}

        # Add a fanfic and then poison pill to stop the loop
        fanfic = fanfic_info.FanficInfo(site="test_site", url="test_url")
        waiting_queue.put(fanfic)
        waiting_queue.put(None)  # Poison pill to stop processing

        # Run the processor
        ff_waiter.wait_processor(processor_queues, waiting_queue)

        # Verify process_fanfic was called with the correct arguments
        mock_process_fanfic.assert_called_once_with(fanfic, processor_queues)

        # Verify sleep was called
        mock_sleep.assert_called_with(5)

    @patch("ff_waiter.process_fanfic")
    @patch("ff_waiter.sleep")
    def test_wait_processor_poison_pill_shutdown(self, mock_sleep, mock_process_fanfic):
        """Test that wait_processor stops when receiving None (poison pill)."""
        waiting_queue = mp.Queue()
        processor_queues = {"test_site": mp.Queue()}

        # Add only poison pill - should stop immediately
        waiting_queue.put(None)

        # Run the processor
        ff_waiter.wait_processor(processor_queues, waiting_queue)

        # Verify process_fanfic was never called
        mock_process_fanfic.assert_not_called()

        # Verify sleep was never called (no processing iteration)
        mock_sleep.assert_not_called()

    @patch("ff_waiter.process_fanfic")
    @patch("ff_waiter.sleep")
    def test_wait_processor_multiple_fanfics(self, mock_sleep, mock_process_fanfic):
        """Test that wait_processor handles multiple fanfics before shutdown."""
        waiting_queue = mp.Queue()
        processor_queues = {"site1": mp.Queue(), "site2": mp.Queue()}

        # Add multiple fanfics and then poison pill
        fanfic1 = fanfic_info.FanficInfo(site="site1", url="url1")
        fanfic2 = fanfic_info.FanficInfo(site="site2", url="url2")
        fanfic3 = fanfic_info.FanficInfo(site="site1", url="url3")

        waiting_queue.put(fanfic1)
        waiting_queue.put(fanfic2)
        waiting_queue.put(fanfic3)
        waiting_queue.put(None)  # Poison pill

        # Run the processor
        ff_waiter.wait_processor(processor_queues, waiting_queue)

        # Verify process_fanfic was called for each fanfic
        expected_calls = [
            call(fanfic1, processor_queues),
            call(fanfic2, processor_queues),
            call(fanfic3, processor_queues),
        ]
        mock_process_fanfic.assert_has_calls(expected_calls)
        self.assertEqual(mock_process_fanfic.call_count, 3)

        # Verify sleep was called 3 times (once per fanfic)
        self.assertEqual(mock_sleep.call_count, 3)
        mock_sleep.assert_called_with(5)


if __name__ == "__main__":
    unittest.main()
