import unittest
from unittest.mock import MagicMock, patch
from services import supervisor
from models.context import SharedIPCContext


class TestSupervisor(unittest.TestCase):
    def setUp(self):
        self.worker_queues = {"worker_1": MagicMock()}
        self.ingress_queue = MagicMock()
        self.waiting_queue = MagicMock()
        self.email_info = MagicMock()
        self.notification_info = MagicMock()
        self.url_parsers = {}
        self.active_urls = {}
        self.mock_history_recorder = MagicMock()
        self.mock_config_store = MagicMock()
        self.ipc = SharedIPCContext(
            ingress_queue=self.ingress_queue,
            waiting_queue=self.waiting_queue,
            worker_queues=self.worker_queues,
            active_urls=self.active_urls,
            history_recorder=self.mock_history_recorder,
            config_store=self.mock_config_store,
            verbose=False,
        )

    @patch("services.supervisor.ff_logging")
    @patch("threading.Thread")
    @patch("services.supervisor.time.sleep")
    @patch("services.supervisor.signal.signal")
    def test_run_supervisor_starts_threads(
        self, mock_signal, mock_sleep, mock_thread, mock_logging
    ):
        """Test that run_supervisor starts the expected threads."""
        mock_event = MagicMock()
        mock_event.is_set.side_effect = [False, True, True, True, True]
        self.ipc.verbose = True

        with patch("threading.Event", return_value=mock_event):
            supervisor.run_supervisor(
                self.ipc,
                self.email_info,
                self.notification_info,
                self.url_parsers,
            )

        self.assertEqual(mock_thread.call_count, 3)

        targets = [call_args[1]["target"] for call_args in mock_thread.call_args_list]
        self.assertTrue(any("email_watcher" in str(t) for t in targets))
        self.assertTrue(any("wait_processor" in str(t) for t in targets))
        self.assertTrue(any("start_coordinator" in str(t) for t in targets))

        for thread_mock in (mock_thread.return_value,):
            thread_mock.start.assert_called()

        mock_logging.init_process_logging.assert_called_once_with(
            True,
            color="\033[92m",
            log_queue=None,
            config_store=self.mock_config_store,
            is_web_server=False,
        )

    @patch("services.supervisor.ff_logging")
    @patch("threading.Thread")
    @patch("services.supervisor.time.sleep")
    @patch("services.supervisor.signal.signal")
    def test_run_supervisor_enables_web_logging_when_log_queue_provided(
        self, mock_signal, mock_sleep, mock_thread, mock_logging
    ):
        """Supervisor passes log_queue and config_store into init_process_logging."""
        mock_event = MagicMock()
        mock_event.is_set.side_effect = [True]
        mock_log_queue = MagicMock()
        self.ipc.log_queue = mock_log_queue

        with patch("threading.Event", return_value=mock_event):
            supervisor.run_supervisor(
                self.ipc,
                self.email_info,
                self.notification_info,
                self.url_parsers,
            )

        mock_logging.init_process_logging.assert_called_once_with(
            False,
            color="\033[92m",
            log_queue=mock_log_queue,
            config_store=self.mock_config_store,
            is_web_server=False,
        )

        mock_logging.reset_mock()
        mock_event.is_set.side_effect = [True]
        mock_store = MagicMock()
        self.ipc.log_queue = None
        self.ipc.config_store = mock_store
        with patch("threading.Event", return_value=mock_event):
            supervisor.run_supervisor(
                self.ipc,
                self.email_info,
                self.notification_info,
                self.url_parsers,
            )
        mock_logging.init_process_logging.assert_called_once_with(
            False,
            color="\033[92m",
            log_queue=None,
            config_store=mock_store,
            is_web_server=False,
        )

    @patch("services.supervisor.ff_logging")
    @patch("threading.Thread")
    @patch("services.supervisor.time.sleep")
    @patch("services.supervisor.signal.signal")
    def test_run_supervisor_detects_dead_thread(
        self, mock_signal, mock_sleep, mock_thread, mock_logging
    ):
        """Test that supervisor detects a dead thread and shuts down."""
        t1 = MagicMock()
        t2 = MagicMock()
        t3 = MagicMock()
        mock_thread.side_effect = [t1, t2, t3]

        t1.is_alive.return_value = False
        t2.is_alive.return_value = True
        t3.is_alive.return_value = True

        mock_event = MagicMock()
        mock_event.is_set.return_value = False

        def set_effect():
            mock_event.is_set.return_value = True

        mock_event.set.side_effect = set_effect

        with patch("threading.Event", return_value=mock_event):
            supervisor.run_supervisor(
                self.ipc,
                self.email_info,
                self.notification_info,
                self.url_parsers,
            )

        mock_logging.log_failure.assert_called()
        mock_event.set.assert_called()


if __name__ == "__main__":
    unittest.main()
