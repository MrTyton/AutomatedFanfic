import unittest
from unittest.mock import MagicMock, patch, call, ANY
import signal
import multiprocessing as mp

from workers import pool_runner, pipeline
from calibre_integration import calibredb_utils
from notifications import notification_wrapper
from models import config_models
from models.context import SharedIPCContext, WorkerContext


class TestPoolRunner(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock(spec=calibredb_utils.CalibreDBClient)
        self.mock_notification = MagicMock(
            spec=notification_wrapper.NotificationWrapper
        )
        self.mock_waiting_queue = MagicMock(spec=mp.Queue)
        self.mock_ingress_queue = MagicMock()
        self.mock_retry_config = MagicMock(spec=config_models.RetryConfig)
        self.active_urls = {}

        self.worker_queues = {
            "worker_1": MagicMock(spec=mp.Queue),
            "worker_2": MagicMock(spec=mp.Queue),
        }
        self.mock_history_recorder = MagicMock()
        self.mock_config_store = MagicMock()
        self.ipc = SharedIPCContext(
            ingress_queue=self.mock_ingress_queue,
            waiting_queue=self.mock_waiting_queue,
            worker_queues=self.worker_queues,
            active_urls=self.active_urls,
            history_recorder=self.mock_history_recorder,
            config_store=self.mock_config_store,
            verbose=False,
        )

    @patch("workers.pool_runner.threading.Thread")
    @patch("workers.pool_runner.signal.signal")
    @patch("workers.pool_runner.ff_logging")
    @patch("workers.pool_runner.threading.Event")
    def test_run_worker_pool_initialization(
        self, mock_event_cls, mock_logging, mock_signal, mock_thread_cls
    ):
        """Test that worker pool initializes correctly spawning threads."""
        mock_shutdown_event = MagicMock()
        mock_shutdown_event.is_set.side_effect = [False, True]
        mock_event_cls.return_value = mock_shutdown_event

        def make_named_thread(**kwargs):
            t = MagicMock()
            t.name = kwargs.get("name", "unknown")
            t.is_alive.return_value = True
            return t

        mock_thread_cls.side_effect = lambda *args, **kwargs: make_named_thread(
            **kwargs
        )
        self.ipc.verbose = True

        pool_runner.run_worker_pool(
            self.ipc,
            self.mock_client,
            self.mock_notification,
            self.mock_retry_config,
        )

        # Verify logging setup
        mock_logging.init_process_logging.assert_called_once_with(
            True,
            log_queue=None,
            config_store=self.mock_config_store,
            is_web_server=False,
        )

        # Verify signal handlers registered
        mock_signal.assert_has_calls(
            [call(signal.SIGINT, ANY), call(signal.SIGTERM, ANY)]
        )

        # Verify threads created
        self.assertEqual(mock_thread_cls.call_count, 2)

        call_args_list = mock_thread_cls.call_args_list
        worker_ids_found = []
        for call_args in call_args_list:
            _, kwargs = call_args
            worker_ids_found.append(kwargs["name"])
            self.assertEqual(kwargs["target"], pipeline.url_worker)
            self.assertTrue(kwargs["daemon"])
            self.assertIsInstance(kwargs["args"][1], WorkerContext)

        self.assertCountEqual(worker_ids_found, ["worker_1", "worker_2"])

    @patch("workers.pool_runner.threading.Thread")
    @patch("workers.pool_runner.time.sleep")
    @patch("workers.pool_runner.threading.Event")
    def test_run_worker_pool_thread_restart(
        self, mock_event_cls, mock_sleep, mock_thread_cls
    ):
        """Test that dead threads are restarted."""
        mock_shutdown_event = MagicMock()
        mock_shutdown_event.is_set.side_effect = [False, False, True, True, True]
        mock_event_cls.return_value = mock_shutdown_event

        thread1 = MagicMock()
        thread1.name = "worker_1"
        thread2 = MagicMock()
        thread2.name = "worker_2"

        thread1.is_alive.return_value = True
        thread2.is_alive.return_value = False

        thread2_replacement = MagicMock()
        thread2_replacement.name = "worker_2"

        mock_thread_cls.side_effect = [
            thread1,
            thread2,
            thread2_replacement,
            MagicMock(),
        ]

        pool_runner.run_worker_pool(
            self.ipc,
            self.mock_client,
            self.mock_notification,
            self.mock_retry_config,
        )

        self.assertEqual(mock_thread_cls.call_count, 3)

        _args, kwargs = mock_thread_cls.call_args_list[2]
        self.assertEqual(kwargs["name"], "worker_2")

        thread2_replacement.start.assert_called_once()

    @patch("workers.pool_runner.signal.signal")
    @patch("workers.pool_runner.threading.Event")
    def test_run_worker_pool_shutdown_signal(self, mock_event_cls, mock_signal):
        """Test proper signal handling."""
        mock_shutdown_event = MagicMock()
        mock_shutdown_event.is_set.side_effect = [True]
        mock_event_cls.return_value = mock_shutdown_event
        self.ipc.worker_queues = {}

        pool_runner.run_worker_pool(
            self.ipc,
            self.mock_client,
            self.mock_notification,
            self.mock_retry_config,
        )

        handler = mock_signal.call_args_list[0][0][1]
        handler(signal.SIGINT, None)
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
        mock_shutdown_event.is_set.return_value = False
        mock_event_cls.return_value = mock_shutdown_event

        mock_sleep.side_effect = KeyboardInterrupt

        pool_runner.run_worker_pool(
            self.ipc,
            self.mock_client,
            self.mock_notification,
            self.mock_retry_config,
        )

        mock_logging.log.assert_called_with("Worker Pool interrupted", "WARNING")
        mock_logging.log_debug.assert_called_with(
            "Worker Pool shutting down threads..."
        )

    @patch("workers.pool_runner.threading.Thread")
    @patch("workers.pool_runner.time.sleep")
    @patch("workers.pool_runner.ff_logging")
    @patch("workers.pool_runner.threading.Event")
    def test_run_worker_pool_web_enabled_and_sleep_interval(
        self, mock_event_cls, mock_logging, mock_sleep, mock_thread_cls
    ):
        """Worker pool configures logging via init_process_logging and sleeps 2.0s per health check iteration."""
        mock_shutdown_event = MagicMock()
        mock_shutdown_event.is_set.side_effect = [False, True]
        mock_event_cls.return_value = mock_shutdown_event
        mock_log_queue = MagicMock()
        self.ipc.worker_queues = {}
        self.ipc.log_queue = mock_log_queue

        pool_runner.run_worker_pool(
            self.ipc,
            self.mock_client,
            self.mock_notification,
            self.mock_retry_config,
        )

        mock_logging.init_process_logging.assert_called_once_with(
            False,
            log_queue=mock_log_queue,
            config_store=self.mock_config_store,
            is_web_server=False,
        )
        mock_sleep.assert_called_once_with(2.0)

    @patch("workers.pool_runner.threading.Thread")
    def test_spawn_worker_thread_creates_and_starts_daemon_thread(
        self, mock_thread_cls
    ):
        """_spawn_worker_thread passes (queue, ctx, worker_id, verbose) to pipeline.url_worker and starts the daemon thread."""
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread
        ctx = WorkerContext(
            calibre_client=self.mock_client,
            notification_info=self.mock_notification,
            ingress_queue=self.mock_ingress_queue,
            waiting_queue=self.mock_waiting_queue,
            retry_config=self.mock_retry_config,
            history_recorder=self.mock_history_recorder,
            active_urls=self.active_urls,
        )
        q = self.worker_queues["worker_1"]

        result = pool_runner._spawn_worker_thread("worker_1", q, ctx, True)

        self.assertIs(result, mock_thread)
        mock_thread_cls.assert_called_once_with(
            target=pipeline.url_worker,
            args=(q, ctx, "worker_1", True),
            name="worker_1",
            daemon=True,
        )
        mock_thread.start.assert_called_once()
