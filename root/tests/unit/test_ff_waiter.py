import multiprocessing as mp
import threading
import unittest
from unittest.mock import patch


from models import fanfic_info
from services import ff_waiter
from models import retry_types


class TestLogRetryDecision(unittest.TestCase):
    """Test the _log_retry_decision helper function."""

    @patch("services.ff_waiter.ff_logging.log")
    def test_retry_action_logs_waiting(self, mock_log):
        fanfic = fanfic_info.FanficInfo(site="site", url="url", repeats=3)
        decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.RETRY,
            delay_minutes=5.0,
            should_notify=False,
            notification_message="",
        )

        ff_waiter._log_retry_decision(fanfic, decision)

        mock_log.assert_called_once()
        self.assertIn("Waiting ~5.00 minutes", mock_log.call_args[0][0])
        self.assertIn("retry #3", mock_log.call_args[0][0])

    @patch("services.ff_waiter.ff_logging.log")
    def test_hail_mary_action_logs_hail_mary(self, mock_log):
        fanfic = fanfic_info.FanficInfo(site="site", url="url")
        decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.HAIL_MARY,
            delay_minutes=720.0,
            should_notify=False,
            notification_message="",
        )

        ff_waiter._log_retry_decision(fanfic, decision)

        mock_log.assert_called_once()
        self.assertIn("Hail-Mary attempt", mock_log.call_args[0][0])

    @patch("services.ff_waiter.ff_logging.log")
    def test_abandon_action_logs_error(self, mock_log):
        fanfic = fanfic_info.FanficInfo(site="site", url="url")
        decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.ABANDON,
            delay_minutes=0.0,
            should_notify=False,
            notification_message="",
        )

        ff_waiter._log_retry_decision(fanfic, decision)

        mock_log.assert_called_once()
        self.assertIn("Unexpected abandon action", mock_log.call_args[0][0])
        self.assertEqual("ERROR", mock_log.call_args[0][1])


class TestGetDelaySeconds(unittest.TestCase):
    """Test the _get_delay_seconds helper function."""

    @patch("services.ff_waiter.ff_logging.log")
    def test_retry_returns_delay(self, mock_log):
        fanfic = fanfic_info.FanficInfo(site="site", url="url", repeats=2)
        fanfic.retry_decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.RETRY,
            delay_minutes=5.0,
            should_notify=False,
            notification_message="",
        )

        delay = ff_waiter._get_delay_seconds(fanfic)
        self.assertEqual(delay, 300)

    @patch("services.ff_waiter.ff_logging.log")
    def test_hail_mary_returns_delay(self, mock_log):
        fanfic = fanfic_info.FanficInfo(site="site", url="url")
        fanfic.retry_decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.HAIL_MARY,
            delay_minutes=720.0,
            should_notify=False,
            notification_message="",
        )

        delay = ff_waiter._get_delay_seconds(fanfic)
        self.assertEqual(delay, 43200)

    @patch("services.ff_waiter.ff_logging.log")
    def test_abandon_returns_none(self, mock_log):
        fanfic = fanfic_info.FanficInfo(site="site", url="url")
        fanfic.retry_decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.ABANDON,
            delay_minutes=0.0,
            should_notify=False,
            notification_message="",
        )

        delay = ff_waiter._get_delay_seconds(fanfic)
        self.assertIsNone(delay)

    @patch("services.ff_waiter.ff_logging.log")
    def test_no_decision_uses_fallback(self, mock_log):
        fanfic = fanfic_info.FanficInfo(site="site", url="url")
        # No retry_decision set (None)

        delay = ff_waiter._get_delay_seconds(fanfic)

        self.assertEqual(delay, 300)  # 5 min default
        # First log call should be the warning about missing decision
        self.assertIn("No retry decision found", mock_log.call_args_list[0][0][0])

    @patch("services.ff_waiter.ff_logging.log")
    def test_fractional_delay(self, mock_log):
        fanfic = fanfic_info.FanficInfo(site="site", url="url", repeats=1)
        fanfic.retry_decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.RETRY,
            delay_minutes=10.5,
            should_notify=False,
            notification_message="",
        )

        delay = ff_waiter._get_delay_seconds(fanfic)
        self.assertEqual(delay, 630)


class TestWaitProcessor(unittest.TestCase):
    """Test the wait_processor function with heap-based scheduling."""

    @patch("services.ff_waiter._get_delay_seconds")
    def test_wait_processor_processes_fanfics(self, mock_get_delay):
        """Test that wait_processor schedules items and requeues after delay."""
        mock_get_delay.return_value = 0  # Zero delay = immediate requeue

        waiting_queue = mp.Queue()
        ingress_queue = mp.Queue()

        fanfic = fanfic_info.FanficInfo(site="test_site", url="test_url")
        fanfic.retry_decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.RETRY,
            delay_minutes=0.0,
            should_notify=False,
            notification_message="",
        )
        waiting_queue.put(fanfic)
        waiting_queue.put(None)  # Poison pill

        ff_waiter.wait_processor(ingress_queue, waiting_queue)

        # Item should be requeued to ingress
        result = ingress_queue.get(timeout=2)
        self.assertEqual(result.url, "test_url")

    @patch("services.ff_waiter._get_delay_seconds")
    def test_wait_processor_poison_pill_shutdown(self, mock_get_delay):
        """Test that wait_processor stops when receiving None (poison pill)."""
        waiting_queue = mp.Queue()
        ingress_queue = mp.Queue()

        waiting_queue.put(None)

        ff_waiter.wait_processor(ingress_queue, waiting_queue)

        mock_get_delay.assert_not_called()
        self.assertTrue(ingress_queue.empty())

    @patch("services.ff_waiter._get_delay_seconds")
    def test_wait_processor_multiple_fanfics_ordered(self, mock_get_delay):
        """Test that multiple zero-delay items are all requeued."""
        mock_get_delay.return_value = 0

        waiting_queue = mp.Queue()
        ingress_queue = mp.Queue()

        fanfic1 = fanfic_info.FanficInfo(site="site1", url="url1")
        fanfic2 = fanfic_info.FanficInfo(site="site2", url="url2")
        fanfic3 = fanfic_info.FanficInfo(site="site1", url="url3")

        waiting_queue.put(fanfic1)
        waiting_queue.put(fanfic2)
        waiting_queue.put(fanfic3)
        waiting_queue.put(None)

        ff_waiter.wait_processor(ingress_queue, waiting_queue)

        urls = []
        while not ingress_queue.empty():
            urls.append(ingress_queue.get(timeout=1).url)
        self.assertEqual(sorted(urls), ["url1", "url2", "url3"])

    @patch("services.ff_waiter._get_delay_seconds")
    def test_wait_processor_abandon_items_dropped(self, mock_get_delay):
        """Test that items with ABANDON action (None delay) are dropped."""
        mock_get_delay.return_value = None  # Signals ABANDON

        waiting_queue = mp.Queue()
        ingress_queue = mp.Queue()

        fanfic = fanfic_info.FanficInfo(site="site", url="url")
        waiting_queue.put(fanfic)
        waiting_queue.put(None)

        ff_waiter.wait_processor(ingress_queue, waiting_queue)

        self.assertTrue(ingress_queue.empty())

    def test_wait_processor_shutdown_event(self):
        """Test that wait_processor exits when shutdown_event is set."""
        waiting_queue = mp.Queue()
        ingress_queue = mp.Queue()

        shutdown_event = threading.Event()
        shutdown_event.set()  # Already signaled

        ff_waiter.wait_processor(
            ingress_queue, waiting_queue, shutdown_event=shutdown_event
        )

        # Should exit immediately without processing anything
        self.assertTrue(ingress_queue.empty())

    @patch("services.ff_waiter._get_delay_seconds")
    def test_wait_processor_delayed_items_requeued(self, mock_get_delay):
        """Test that delayed items are requeued after their expiry."""
        # Very small delay (0.05s) to keep test fast
        mock_get_delay.return_value = 0.05

        waiting_queue = mp.Queue()
        ingress_queue = mp.Queue()
        shutdown_event = threading.Event()

        fanfic = fanfic_info.FanficInfo(site="site", url="delayed_url")
        waiting_queue.put(fanfic)

        # Run in a thread so we can shut it down
        def run():
            ff_waiter.wait_processor(
                ingress_queue, waiting_queue, shutdown_event=shutdown_event
            )

        t = threading.Thread(target=run)
        t.start()

        # Wait for the item to be requeued (with generous timeout)
        result = ingress_queue.get(timeout=5)
        self.assertEqual(result.url, "delayed_url")

        # Shut down
        shutdown_event.set()
        t.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
