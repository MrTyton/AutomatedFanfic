import multiprocessing as mp
import threading
import unittest
from unittest.mock import MagicMock, patch


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


def _run_wait_processor(
    ingress_queue,
    waiting_queue,
    verbose=False,
    shutdown_event=None,
    history_recorder=None,
    active_urls=None,
):
    ff_waiter.wait_processor(
        ingress_queue,
        waiting_queue,
        verbose,
        shutdown_event if shutdown_event is not None else threading.Event(),
        history_recorder if history_recorder is not None else MagicMock(),
        active_urls if active_urls is not None else {},
    )


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

        _run_wait_processor(ingress_queue, waiting_queue)

        # Item should be requeued to ingress
        result = ingress_queue.get(timeout=2)
        self.assertEqual(result.url, "test_url")

    @patch("services.ff_waiter._get_delay_seconds")
    def test_wait_processor_poison_pill_shutdown(self, mock_get_delay):
        """Test that wait_processor stops when receiving None (poison pill)."""
        waiting_queue = mp.Queue()
        ingress_queue = mp.Queue()

        waiting_queue.put(None)

        _run_wait_processor(ingress_queue, waiting_queue)

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

        _run_wait_processor(ingress_queue, waiting_queue)

        urls = []
        for _ in range(3):
            urls.append(ingress_queue.get(timeout=2).url)
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

        _run_wait_processor(ingress_queue, waiting_queue)

        self.assertTrue(ingress_queue.empty())

    def test_wait_processor_shutdown_event(self):
        """Test that wait_processor exits when shutdown_event is set."""
        waiting_queue = mp.Queue()
        ingress_queue = mp.Queue()

        shutdown_event = threading.Event()
        shutdown_event.set()  # Already signaled

        _run_wait_processor(ingress_queue, waiting_queue, shutdown_event=shutdown_event)

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
            _run_wait_processor(
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


class TestWaitProcessorHeapGen(unittest.TestCase):
    """Tests for the heap generation token (cancel/stale detection) behaviour.

    When wait_processor schedules a heap entry it writes a ``heap_gen`` token
    to ``active_urls``.  On expiry the stored token is compared against the
    current active_urls value:

    - **match** and status != "cancelled" → item requeued normally.
    - **mismatch** (e.g. retry-now wrote a fresh dict without ``heap_gen``) →
      stale; entry dropped, active_urls left intact so the new queued entry
      survives.
    - **match** but status == "cancelled" (cancel-retry wrote the status after
      scheduling) → entry dropped and the active_urls entry deleted.
    """

    def _fanfic(self, url: str) -> fanfic_info.FanficInfo:
        fanfic = fanfic_info.FanficInfo(site="site", url=url)
        fanfic.retry_decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.RETRY,
            delay_minutes=0.0,
            should_notify=False,
            notification_message="",
        )
        return fanfic

    # ------------------------------------------------------------------ #
    # Scheduling: heap_gen written to active_urls                         #
    # ------------------------------------------------------------------ #

    @patch("services.ff_waiter._get_delay_seconds")
    def test_heap_gen_written_to_active_urls_on_scheduling(self, mock_get_delay):
        """wait_processor writes heap_gen=0 to active_urls for the first item."""
        mock_get_delay.return_value = 100  # large delay: item stays on heap

        wq, iq = mp.Queue(), mp.Queue()
        active_urls: dict = {}
        fanfic = self._fanfic("http://example.com/a")
        wq.put(fanfic)
        wq.put(None)

        _run_wait_processor(iq, wq, active_urls=active_urls)

        self.assertIn(fanfic.url, active_urls)
        self.assertEqual(active_urls[fanfic.url].get("heap_gen"), 0)

    @patch("services.ff_waiter._get_delay_seconds")
    def test_heap_gen_increments_per_item(self, mock_get_delay):
        """Each scheduled item receives a unique, incrementing heap_gen token."""
        mock_get_delay.return_value = 100

        wq, iq = mp.Queue(), mp.Queue()
        active_urls: dict = {}
        fanfic1 = self._fanfic("http://example.com/b1")
        fanfic2 = self._fanfic("http://example.com/b2")
        wq.put(fanfic1)
        wq.put(fanfic2)
        wq.put(None)

        _run_wait_processor(iq, wq, active_urls=active_urls)

        gen1 = active_urls[fanfic1.url]["heap_gen"]
        gen2 = active_urls[fanfic2.url]["heap_gen"]
        self.assertNotEqual(gen1, gen2)

    # ------------------------------------------------------------------ #
    # Firing: normal (matching heap_gen) requeues                         #
    # ------------------------------------------------------------------ #

    @patch("services.ff_waiter._get_delay_seconds")
    def test_normal_item_requeued_with_matching_heap_gen(self, mock_get_delay):
        """Item whose heap_gen still matches active_urls is forwarded to ingress."""
        mock_get_delay.return_value = 0

        wq, iq = mp.Queue(), mp.Queue()
        active_urls: dict = {}
        fanfic = self._fanfic("http://example.com/c")
        wq.put(fanfic)
        wq.put(None)

        _run_wait_processor(iq, wq, active_urls=active_urls)

        result = iq.get(timeout=2)
        self.assertEqual(result.url, fanfic.url)
        self.assertTrue(iq.empty())

    # ------------------------------------------------------------------ #
    # Firing: stale entry (retry-now scenario) is dropped                 #
    # ------------------------------------------------------------------ #

    @patch("services.ff_waiter._get_delay_seconds")
    def test_stale_entry_dropped_simulating_retry_now(self, mock_get_delay):
        """Stale heap entry is dropped when active_urls no longer carries heap_gen.

        Reproduces the retry-now scenario: the UI replaces active_urls[url] with
        a fresh dict (no heap_gen) while the old entry sits on the heap.
        """
        mock_get_delay.return_value = 0

        wq, iq = mp.Queue(), mp.Queue()

        class RetryNowUrls(dict):
            """After heap_gen is written, replace with a fresh dict (no heap_gen)."""

            def __setitem__(self, key, value):
                super().__setitem__(key, value)
                if isinstance(value, dict) and "heap_gen" in value:
                    super().__setitem__(key, {"status": "queued", "site": "site"})

        active_urls = RetryNowUrls()
        fanfic = self._fanfic("http://example.com/d")
        wq.put(fanfic)
        wq.put(None)

        _run_wait_processor(iq, wq, active_urls=active_urls)

        # Old heap entry must be dropped — ingress queue stays empty
        self.assertTrue(iq.empty())

    @patch("services.ff_waiter._get_delay_seconds")
    def test_stale_entry_does_not_delete_active_urls_entry(self, mock_get_delay):
        """Dropping a stale entry leaves active_urls intact.

        The fresh 'queued' dict written by retry-now must not be deleted;
        it belongs to the newly-enqueued item, not the stale heap entry.
        """
        mock_get_delay.return_value = 0

        wq, iq = mp.Queue(), mp.Queue()

        class RetryNowUrls(dict):
            def __setitem__(self, key, value):
                super().__setitem__(key, value)
                if isinstance(value, dict) and "heap_gen" in value:
                    super().__setitem__(key, {"status": "queued", "site": "site"})

        active_urls = RetryNowUrls()
        fanfic = self._fanfic("http://example.com/e")
        wq.put(fanfic)
        wq.put(None)

        _run_wait_processor(iq, wq, active_urls=active_urls)

        self.assertIn(fanfic.url, active_urls)
        self.assertEqual(active_urls[fanfic.url].get("status"), "queued")

    # ------------------------------------------------------------------ #
    # Firing: cancelled entry is dropped and cleaned up                   #
    # ------------------------------------------------------------------ #

    @patch("services.ff_waiter._get_delay_seconds")
    def test_cancelled_entry_is_not_requeued(self, mock_get_delay):
        """Heap entry with matching heap_gen but status='cancelled' is dropped.

        Reproduces the cancel-retry scenario: the UI keeps heap_gen intact but
        sets status='cancelled' on the active_urls entry.
        """
        mock_get_delay.return_value = 0

        wq, iq = mp.Queue(), mp.Queue()

        class CancelUrls(dict):
            """Preserve heap_gen but inject status='cancelled' after scheduling."""

            def __setitem__(self, key, value):
                super().__setitem__(key, value)
                if isinstance(value, dict) and "heap_gen" in value:
                    merged = dict(value)
                    merged["status"] = "cancelled"
                    super().__setitem__(key, merged)

        active_urls = CancelUrls()
        fanfic = self._fanfic("http://example.com/f")
        wq.put(fanfic)
        wq.put(None)

        _run_wait_processor(iq, wq, active_urls=active_urls)

        self.assertTrue(iq.empty())

    @patch("services.ff_waiter._get_delay_seconds")
    def test_cancelled_entry_is_removed_from_active_urls(self, mock_get_delay):
        """Dropping a cancelled entry deletes it from active_urls (UI cleanup)."""
        mock_get_delay.return_value = 0

        wq, iq = mp.Queue(), mp.Queue()

        class CancelUrls(dict):
            def __setitem__(self, key, value):
                super().__setitem__(key, value)
                if isinstance(value, dict) and "heap_gen" in value:
                    merged = dict(value)
                    merged["status"] = "cancelled"
                    super().__setitem__(key, merged)

        active_urls = CancelUrls()
        fanfic = self._fanfic("http://example.com/g")
        wq.put(fanfic)
        wq.put(None)

        _run_wait_processor(iq, wq, active_urls=active_urls)

        self.assertNotIn(fanfic.url, active_urls)

    @patch("services.ff_waiter._get_delay_seconds")
    def test_cancelled_entry_does_not_call_history_recorder(self, mock_get_delay):
        """history_recorder.record_retry_fired is NOT called when an entry is dropped."""
        mock_get_delay.return_value = 0

        wq, iq = mp.Queue(), mp.Queue()

        class CancelUrls(dict):
            def __setitem__(self, key, value):
                super().__setitem__(key, value)
                if isinstance(value, dict) and "heap_gen" in value:
                    merged = dict(value)
                    merged["status"] = "cancelled"
                    super().__setitem__(key, merged)

        recorder = MagicMock()
        active_urls = CancelUrls()
        fanfic = self._fanfic("http://example.com/h")
        wq.put(fanfic)
        wq.put(None)

        _run_wait_processor(iq, wq, active_urls=active_urls, history_recorder=recorder)

        recorder.record_retry_fired.assert_not_called()

    # ------------------------------------------------------------------ #
    # Mixed scenario                                                       #
    # ------------------------------------------------------------------ #

    @patch("services.ff_waiter._get_delay_seconds")
    def test_mixed_items_selective_drop(self, mock_get_delay):
        """Normal, stale, and cancelled items coexist: only the normal one requeues."""
        mock_get_delay.return_value = 0

        wq, iq = mp.Queue(), mp.Queue()

        stale_url = "http://example.com/stale"
        cancelled_url = "http://example.com/cancelled"

        class MixedUrls(dict):
            def __setitem__(self, key, value):
                super().__setitem__(key, value)
                if isinstance(value, dict) and "heap_gen" in value:
                    if key == cancelled_url:
                        merged = dict(value)
                        merged["status"] = "cancelled"
                        super().__setitem__(key, merged)
                    elif key == stale_url:
                        super().__setitem__(key, {"status": "queued"})

        active_urls = MixedUrls()
        fanfic_normal = self._fanfic("http://example.com/normal")
        fanfic_stale = self._fanfic(stale_url)
        fanfic_cancelled = self._fanfic(cancelled_url)

        for f in [fanfic_normal, fanfic_stale, fanfic_cancelled]:
            wq.put(f)
        wq.put(None)

        _run_wait_processor(iq, wq, active_urls=active_urls)

        results = []
        try:
            results.append(iq.get(timeout=2).url)
        except Exception:
            pass
        while True:
            try:
                results.append(iq.get_nowait().url)
            except Exception:
                break
        self.assertEqual(results, ["http://example.com/normal"])
        # Cancelled entry must be cleaned up
        self.assertNotIn(cancelled_url, active_urls)
        # Stale entry must remain (it holds the fresh queued dict from retry-now)
        self.assertIn(stale_url, active_urls)
        self.assertEqual(active_urls[stale_url].get("status"), "queued")


if __name__ == "__main__":
    unittest.main()
