import unittest
from unittest.mock import MagicMock, patch, call, ANY
import signal
import multiprocessing as mp

from workers import pool_runner, pipeline
from calibre_integration import calibredb_utils
from notifications import notification_wrapper
from models import config_models


class TestPoolRunner(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock(spec=calibredb_utils.CalibreDBClient)
        self.mock_notification = MagicMock(
            spec=notification_wrapper.NotificationWrapper
        )
        self.mock_waiting_queue = MagicMock(spec=mp.Queue)
        self.mock_retry_config = MagicMock(spec=config_models.RetryConfig)
        self.active_urls = {}

        self.worker_queues = {
            "worker_1": MagicMock(spec=mp.Queue),
            "worker_2": MagicMock(spec=mp.Queue),
        }

    @patch("workers.pool_runner.threading.Thread")
    @patch("workers.pool_runner.signal.signal")
    @patch("workers.pool_runner.ff_logging")
    @patch("workers.pool_runner.threading.Event")
    def test_run_worker_pool_initialization(
        self, mock_event_cls, mock_logging, mock_signal, mock_thread_cls
    ):
        """Test that worker pool initializes correctly spawning threads."""
        mock_shutdown_event = MagicMock()
        mock_shutdown_event.is_set.side_effect = [False, True]  # Run loop once
        mock_event_cls.return_value = mock_shutdown_event

        pool_runner.run_worker_pool(
            self.worker_queues,
            self.mock_client,
            self.mock_notification,
            self.mock_waiting_queue,
            self.mock_retry_config,
            self.active_urls,
            verbose=True,
        )

        # Verify logging setup
        mock_logging.set_verbose.assert_called_once_with(True)

        # Verify signal handlers registered
        mock_signal.assert_has_calls(
            [call(signal.SIGINT, ANY), call(signal.SIGTERM, ANY)]
        )

        # Verify threads created
        self.assertEqual(mock_thread_cls.call_count, 2)

        # Verify arguments passed to threads
        # We can't guarantee order of dict items, so check that both workers are present in calls
        call_args_list = mock_thread_cls.call_args_list
        worker_ids_found = []
        for call_args in call_args_list:
            _, kwargs = call_args
            worker_ids_found.append(kwargs["name"])
            self.assertEqual(kwargs["target"], pipeline.url_worker)
            self.assertTrue(kwargs["daemon"])

        self.assertCountEqual(worker_ids_found, ["worker_1", "worker_2"])

    @patch("workers.pool_runner.threading.Thread")
    @patch("workers.pool_runner.time.sleep")
    @patch("workers.pool_runner.threading.Event")
    def test_run_worker_pool_thread_restart(
        self, mock_event_cls, mock_sleep, mock_thread_cls
    ):
        """Test that dead threads are restarted."""
        mock_shutdown_event = MagicMock()
        # Loop sequence:
        # 1. Not set (initial check)
        # 2. Not set (after restart check - loops again)
        # 3. Set (exit)
        # Padding with extra Trues just in case of logic shifts
        mock_shutdown_event.is_set.side_effect = [False, False, True, True, True]
        mock_event_cls.return_value = mock_shutdown_event

        # Setup mock threads
        # Initial creation: 2 threads
        thread1 = MagicMock()
        thread1.name = "worker_1"
        thread2 = MagicMock()
        thread2.name = "worker_2"

        # Scenario: thread1 stays alive, thread2 dies
        thread1.is_alive.return_value = True
        thread2.is_alive.return_value = False  # Dies on check

        # Replacement thread
        thread2_replacement = MagicMock(name="worker_2 (new)")

        # mock_thread_cls will be called:
        # 1. Init worker_1
        # 2. Init worker_2
        # 3. Restart worker_2
        # 4. Padding just in case
        mock_thread_cls.side_effect = [
            thread1,
            thread2,
            thread2_replacement,
            MagicMock(),
        ]

        pool_runner.run_worker_pool(
            self.worker_queues,
            self.mock_client,
            self.mock_notification,
            self.mock_waiting_queue,
            self.mock_retry_config,
            self.active_urls,
        )

        # Verify initial creation (2 calls) + restart (1 call) = 3 total
        self.assertEqual(mock_thread_cls.call_count, 3)

        # Verify the 3rd call was for worker_2
        args, kwargs = mock_thread_cls.call_args_list[2]
        self.assertEqual(kwargs["name"], "worker_2")

        # Verify replacement started
        thread2_replacement.start.assert_called_once()

    @patch("workers.pool_runner.signal.signal")
    @patch("workers.pool_runner.threading.Event")
    def test_run_worker_pool_shutdown_signal(self, mock_event_cls, mock_signal):
        """Test proper signal handling."""
        mock_shutdown_event = MagicMock()
        mock_shutdown_event.is_set.side_effect = [True]  # Exit immediately
        mock_event_cls.return_value = mock_shutdown_event

        pool_runner.run_worker_pool(
            {},  # No workers for this test
            self.mock_client,
            self.mock_notification,
            self.mock_waiting_queue,
            self.mock_retry_config,
            self.active_urls,
        )

        # Capture the signal handler function defined inside the function
        # mock_signal calls: (SIGINT, handler), (SIGTERM, handler)
        handler = mock_signal.call_args_list[0][0][1]

        # Call the handler
        handler(signal.SIGINT, None)

        # Verify event was set
        mock_shutdown_event.set.assert_called_once()

    @patch("workers.pool_runner.threading.Thread")
    @patch("workers.pool_runner.time.sleep")
    @patch("workers.pool_runner.threading.Event")
    @patch("workers.pool_runner.ff_logging")
    def test_run_worker_pool_keyboard_interrupt(
        self, mock_logging, mock_event_cls, mock_sleep, mock_thread_cls
    ):
        """Test handling of KeyboardInterrupt."""
        mock_shutdown_event = MagicMock()
        mock_shutdown_event.is_set.return_value = False  # Try to run
        mock_event_cls.return_value = mock_shutdown_event

        # Raise KeyboardInterrupt during sleep
        mock_sleep.side_effect = KeyboardInterrupt

        pool_runner.run_worker_pool(
            self.worker_queues,
            self.mock_client,
            self.mock_notification,
            self.mock_waiting_queue,
            self.mock_retry_config,
            self.active_urls,
        )

        mock_logging.log.assert_called_with("Worker Pool interrupted", "WARNING")
        mock_logging.log_debug.assert_called_with(
            "Worker Pool shutting down threads..."
        )
