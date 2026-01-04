import unittest
from unittest.mock import MagicMock, patch
from services import supervisor


class TestSupervisor(unittest.TestCase):
    def setUp(self):
        self.worker_queues = {"worker_1": MagicMock()}
        self.ingress_queue = MagicMock()
        self.waiting_queue = MagicMock()
        self.email_info = MagicMock()
        self.notification_info = MagicMock()
        self.url_parsers = {}
        self.active_urls = {}

    @patch("services.supervisor.ff_logging")
    @patch("threading.Thread")
    @patch("services.supervisor.time.sleep")
    @patch("services.supervisor.signal.signal")
    def test_run_supervisor_starts_threads(
        self, mock_signal, mock_sleep, mock_thread, mock_logging
    ):
        """Test that run_supervisor starts the expected threads."""
        # Setup mocks
        mock_event = MagicMock()
        # is_set sequence: False (start loop), True (end loop)
        mock_event.is_set.side_effect = [False, True, True, True, True]

        with patch("threading.Event", return_value=mock_event):
            supervisor.run_supervisor(
                self.worker_queues,
                self.ingress_queue,
                self.waiting_queue,
                self.email_info,
                self.notification_info,
                self.url_parsers,
                self.active_urls,
                verbose=True,
            )

        # Verify 3 threads created
        self.assertEqual(mock_thread.call_count, 3)

        # Verify thread targets
        targets = [call_args[1]["target"] for call_args in mock_thread.call_args_list]
        self.assertTrue(any("email_watcher" in str(t) for t in targets))
        self.assertTrue(any("wait_processor" in str(t) for t in targets))
        self.assertTrue(any("start_coordinator" in str(t) for t in targets))

        # Verify threads started
        for thread_mock in (mock_thread.return_value,):
            thread_mock.start.assert_called()

    @patch("services.supervisor.ff_logging")
    @patch("threading.Thread")
    @patch("services.supervisor.time.sleep")
    @patch("services.supervisor.signal.signal")
    def test_run_supervisor_detects_dead_thread(
        self, mock_signal, mock_sleep, mock_thread, mock_logging
    ):
        """Test that supervisor detects a dead thread and shuts down."""
        # Setup thread mocks
        t1 = MagicMock()
        t2 = MagicMock()
        t3 = MagicMock()
        mock_thread.side_effect = [t1, t2, t3]

        # t1 dies immediately
        t1.is_alive.return_value = False
        t2.is_alive.return_value = True
        t3.is_alive.return_value = True

        # Setup event
        mock_event = MagicMock()
        # is_set: False (enter loop), False (check loop condition internal) ...
        # The code checks `if not t.is_alive(): shutdown_event.set()`
        mock_event.is_set.return_value = False
        # We need to manually simulate the set() effect or let the loop break by other means
        # Actually, if set() is called, the next is_set() check should reflect that if we were using a real event.
        # Here we can just verify set() is called.

        # To break the infinite loop in test if logic fails, we use side_effect on sleep to raise exception
        # But we expect it to break because we set shutdown_event.set()

        def set_effect():
            mock_event.is_set.return_value = True

        mock_event.set.side_effect = set_effect

        with patch("threading.Event", return_value=mock_event):
            supervisor.run_supervisor(
                self.worker_queues,
                self.ingress_queue,
                self.waiting_queue,
                self.email_info,
                self.notification_info,
                self.url_parsers,
                self.active_urls,
            )

        # Verify failure detected
        mock_logging.log_failure.assert_called()
        # Verify shutdown triggered
        mock_event.set.assert_called()


if __name__ == "__main__":
    unittest.main()
