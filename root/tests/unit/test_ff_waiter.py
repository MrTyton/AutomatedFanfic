import asyncio
from typing import NamedTuple
import unittest
from unittest.mock import patch, call, AsyncMock


from parameterized import parameterized

import fanfic_info
import ff_waiter
import retry_types


class TestProcessFanfic(unittest.IsolatedAsyncioTestCase):
    """Test the process_fanfic function with pre-calculated retry decisions."""

    class ProcessFanficTestCase(NamedTuple):
        action: retry_types.FailureAction
        delay_minutes: float
        expected_delay_seconds: float
        expected_log_pattern: str
        description: str

    @parameterized.expand(
        [
            ProcessFanficTestCase(
                action=retry_types.FailureAction.RETRY,
                delay_minutes=5.0,
                expected_delay_seconds=300.0,
                expected_log_pattern="Waiting ~5.00 minutes for url in queue site (retry #2)",
                description="Regular retry with 5 minute delay",
            ),
            ProcessFanficTestCase(
                action=retry_types.FailureAction.RETRY,
                delay_minutes=10.5,
                expected_delay_seconds=630.0,
                expected_log_pattern="Waiting ~10.50 minutes for url in queue site (retry #2)",
                description="Regular retry with fractional delay",
            ),
            ProcessFanficTestCase(
                action=retry_types.FailureAction.HAIL_MARY,
                delay_minutes=720.0,
                expected_delay_seconds=43200.0,
                expected_log_pattern="Hail-Mary attempt: Waiting 720.0 minutes for url in queue site",
                description="Hail-Mary with 12 hour delay",
            ),
        ]
    )
    @patch("ff_waiter.ff_logging.log")
    @patch("asyncio.create_task")
    async def test_process_fanfic_with_decisions(
        self,
        action,
        delay_minutes,
        expected_delay_seconds,
        expected_log_pattern,
        description,
        mock_create_task,
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

        queue = asyncio.Queue()
        processor_queues = {"site": queue}

        await ff_waiter.process_fanfic(fanfic, processor_queues)

        # Verify the logging contains expected pattern
        mock_log.assert_called_once()
        log_call_args = mock_log.call_args[0]
        self.assertIn(expected_log_pattern, log_call_args[0])
        self.assertEqual("WARNING", log_call_args[1])

        # Verify asyncio.create_task was called
        mock_create_task.assert_called_once()

    @patch("ff_waiter.ff_logging.log")
    @patch("asyncio.create_task")
    async def test_process_fanfic_with_no_decision(self, mock_create_task, mock_log):
        """Test that process_fanfic handles missing retry decision with fallback."""
        fanfic = fanfic_info.FanficInfo(site="site", url="url")
        # No retry_decision set (None)

        queue = asyncio.Queue()
        processor_queues = {"site": queue}

        await ff_waiter.process_fanfic(fanfic, processor_queues)

        # Should log warning about missing decision and retry details
        self.assertEqual(mock_log.call_count, 2)
        first_log_call = mock_log.call_args_list[0]
        self.assertIn("No retry decision found for url", first_log_call[0][0])
        self.assertEqual("WARNING", first_log_call[0][1])

        # Should create async task for retry
        mock_create_task.assert_called_once()

    @patch("ff_waiter.ff_logging.log")
    async def test_process_fanfic_abandon_action(self, mock_log):
        """Test that ABANDON action is handled correctly (should not schedule task)."""
        fanfic = fanfic_info.FanficInfo(site="site", url="url")
        fanfic.retry_decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.ABANDON,
            delay_minutes=0.0,
            should_notify=False,
            notification_message="",
        )

        processor_queues = {"site": asyncio.Queue()}

        with patch("asyncio.create_task") as mock_create_task:
            await ff_waiter.process_fanfic(fanfic, processor_queues)

            # Should log error and not create task
            mock_log.assert_called_once()
            log_call_args = mock_log.call_args[0]
            self.assertIn(
                "Unexpected abandon action in waiting queue", log_call_args[0]
            )
            self.assertEqual("ERROR", log_call_args[1])

            # Task should not be created
            mock_create_task.assert_not_called()


class TestScheduleDelayedRetry(unittest.IsolatedAsyncioTestCase):
    """Test the schedule_delayed_retry function."""

    async def test_schedule_delayed_retry_queue_put(self):
        """Test that schedule_delayed_retry correctly puts fanfic into queue after delay."""
        # Create an async queue
        queue = asyncio.Queue()
        fanfic = fanfic_info.FanficInfo(site="test_site", url="test_url")

        # Use a short delay for testing (0.1 seconds)
        delay_task = asyncio.create_task(
            ff_waiter.schedule_delayed_retry(0.1, queue, fanfic)
        )

        # Queue should be empty initially
        self.assertTrue(queue.empty())

        # Wait for delay to complete
        await delay_task

        # Now fanfic should be in queue
        retrieved_fanfic = await asyncio.wait_for(queue.get(), timeout=1.0)
        self.assertEqual(retrieved_fanfic, fanfic)
        self.assertEqual(retrieved_fanfic.site, "test_site")
        self.assertEqual(retrieved_fanfic.url, "test_url")

    async def test_schedule_delayed_retry_queue_empty_after_get(self):
        """Test that queue is empty after getting the item."""
        queue = asyncio.Queue()
        fanfic = fanfic_info.FanficInfo(site="another_site", url="another_url")

        # Schedule with short delay
        await ff_waiter.schedule_delayed_retry(0.1, queue, fanfic)

        # Get the item
        retrieved_fanfic = await asyncio.wait_for(queue.get(), timeout=1.0)
        self.assertEqual(retrieved_fanfic, fanfic)

        # Queue should now be empty
        self.assertTrue(queue.empty())


class TestWaitProcessor(unittest.IsolatedAsyncioTestCase):
    """Test the wait_processor function."""

    @patch("ff_waiter.process_fanfic")
    async def test_wait_processor_processes_fanfics(self, mock_process_fanfic):
        """Test that wait_processor processes fanfics from the waiting queue."""
        # Make process_fanfic async-aware
        mock_process_fanfic.return_value = asyncio.Future()
        mock_process_fanfic.return_value.set_result(None)
        
        waiting_queue = asyncio.Queue()
        processor_queues = {"test_site": asyncio.Queue()}

        # Add a fanfic and then None to stop the loop
        fanfic = fanfic_info.FanficInfo(site="test_site", url="test_url")
        await waiting_queue.put(fanfic)
        await waiting_queue.put(None)  # Sentinel to stop processing

        # Run the processor
        await ff_waiter.wait_processor(processor_queues, waiting_queue)

        # Verify process_fanfic was called with the correct arguments
        mock_process_fanfic.assert_called_once_with(fanfic, processor_queues)

    @patch("ff_waiter.process_fanfic")
    async def test_wait_processor_sentinel_shutdown(self, mock_process_fanfic):
        """Test that wait_processor stops when receiving None (sentinel)."""
        waiting_queue = asyncio.Queue()
        processor_queues = {"test_site": asyncio.Queue()}

        # Add only sentinel - should stop immediately
        await waiting_queue.put(None)

        # Run the processor
        await ff_waiter.wait_processor(processor_queues, waiting_queue)

        # Verify process_fanfic was never called
        mock_process_fanfic.assert_not_called()

    @patch("ff_waiter.process_fanfic")
    async def test_wait_processor_multiple_fanfics(self, mock_process_fanfic):
        """Test that wait_processor handles multiple fanfics before shutdown."""
        # Make process_fanfic async-aware
        mock_process_fanfic.return_value = asyncio.Future()
        mock_process_fanfic.return_value.set_result(None)
        
        waiting_queue = asyncio.Queue()
        processor_queues = {"site1": asyncio.Queue(), "site2": asyncio.Queue()}

        # Add multiple fanfics and then sentinel
        fanfic1 = fanfic_info.FanficInfo(site="site1", url="url1")
        fanfic2 = fanfic_info.FanficInfo(site="site2", url="url2")
        fanfic3 = fanfic_info.FanficInfo(site="site1", url="url3")

        await waiting_queue.put(fanfic1)
        await waiting_queue.put(fanfic2)
        await waiting_queue.put(fanfic3)
        await waiting_queue.put(None)  # Sentinel

        # Run the processor
        await ff_waiter.wait_processor(processor_queues, waiting_queue)

        # Verify process_fanfic was called for each fanfic
        expected_calls = [
            call(fanfic1, processor_queues),
            call(fanfic2, processor_queues),
            call(fanfic3, processor_queues),
        ]
        mock_process_fanfic.assert_has_calls(expected_calls)
        self.assertEqual(mock_process_fanfic.call_count, 3)


if __name__ == "__main__":
    unittest.main()
