import unittest
from unittest.mock import MagicMock, patch, call, ANY
import signal
import multiprocessing as mp

from queue import Empty
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
        self.mock_scale_queue = MagicMock()
        self.mock_scale_queue.get.side_effect = Empty
        self.ipc = SharedIPCContext(
            ingress_queue=self.mock_ingress_queue,
            waiting_queue=self.mock_waiting_queue,
            worker_queues=self.worker_queues,
            active_urls=self.active_urls,
            history_recorder=self.mock_history_recorder,
            config_store=self.mock_config_store,
            scale_queue=self.mock_scale_queue,
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
    @patch("workers.pool_runner.threading.Event")
    def test_run_worker_pool_thread_restart(self, mock_event_cls, mock_thread_cls):
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
    @patch("workers.pool_runner.threading.Event")
    @patch("workers.pool_runner.ff_logging")
    def test_run_worker_pool_keyboard_interrupt(
        self, mock_logging, mock_event_cls, mock_thread_cls
    ):
        """Test handling of KeyboardInterrupt."""
        mock_shutdown_event = MagicMock()
        mock_shutdown_event.is_set.return_value = False
        mock_event_cls.return_value = mock_shutdown_event

        self.mock_scale_queue.get.side_effect = KeyboardInterrupt

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
    @patch("workers.pool_runner.ff_logging")
    @patch("workers.pool_runner.threading.Event")
    def test_run_worker_pool_web_enabled_and_scale_queue_polling(
        self, mock_event_cls, mock_logging, mock_thread_cls
    ):
        """Worker pool configures logging via init_process_logging and polls scale_queue with 0.2s timeout."""
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
        self.mock_scale_queue.get.assert_called_with(timeout=0.2)

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
            args=(q, ctx, "worker_1", True, None),
            name="worker_1",
            daemon=True,
        )
        mock_thread.start.assert_called_once()

    @patch("workers.pool_runner.threading.Thread")
    def test_spawn_worker_thread_passes_idle_timeout(self, mock_thread_cls):
        """Verify _spawn_worker_thread passes idle_timeout to pipeline.url_worker."""
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

        result = pool_runner._spawn_worker_thread(
            "worker_1", q, ctx, False, idle_timeout=60.0
        )

        self.assertIs(result, mock_thread)
        mock_thread_cls.assert_called_once_with(
            target=pipeline.url_worker,
            args=(q, ctx, "worker_1", False, 60.0),
            name="worker_1",
            daemon=True,
        )
        mock_thread.start.assert_called_once()

    @patch("workers.pool_runner._spawn_worker_thread")
    @patch("workers.pool_runner.threading.Event")
    def test_pool_runner_spawns_worker_0_initially_and_scales_worker_1_on_signal(
        self, mock_event_cls, mock_spawn
    ):
        """Verify worker_0 is spawned initially with idle_timeout=None, and worker_1 on scale_queue signal with 60.0s."""
        mock_shutdown_event = MagicMock()
        mock_shutdown_event.is_set.side_effect = [False, False, True]
        mock_event_cls.return_value = mock_shutdown_event

        t0 = MagicMock()
        t0.is_alive.return_value = True
        t1 = MagicMock()
        t1.is_alive.return_value = True
        mock_spawn.side_effect = [t0, t1]

        q0 = MagicMock(spec=mp.Queue)
        q1 = MagicMock(spec=mp.Queue)
        scale_q = MagicMock()
        scale_q.get.side_effect = ["worker_1", Empty]
        scale_q.get_nowait.side_effect = Empty

        self.ipc.worker_queues = {"worker_0": q0, "worker_1": q1}
        self.ipc.scale_queue = scale_q

        pool_runner.run_worker_pool(
            self.ipc,
            self.mock_client,
            self.mock_notification,
            self.mock_retry_config,
        )

        self.assertEqual(mock_spawn.call_count, 2)
        # First call: initial spawn of worker_0
        self.assertEqual(mock_spawn.call_args_list[0][0][0], "worker_0")
        self.assertEqual(mock_spawn.call_args_list[0][0][1], q0)
        self.assertIsNone(mock_spawn.call_args_list[0][1].get("idle_timeout"))
        # Second call: scaled worker_1
        self.assertEqual(mock_spawn.call_args_list[1][0][0], "worker_1")
        self.assertEqual(mock_spawn.call_args_list[1][0][1], q1)
        self.assertEqual(mock_spawn.call_args_list[1][1].get("idle_timeout"), 60.0)

    @patch("workers.pool_runner.ff_logging")
    @patch("workers.pool_runner._spawn_worker_thread")
    @patch("workers.pool_runner.threading.Event")
    def test_pool_runner_does_not_restart_stopped_burst_worker(
        self, mock_event_cls, mock_spawn, mock_logging
    ):
        """Verify that when a burst worker (worker_1) stops, it is removed and not restarted."""
        mock_shutdown_event = MagicMock()
        mock_shutdown_event.is_set.side_effect = [False, False, True]
        mock_event_cls.return_value = mock_shutdown_event

        t0 = MagicMock()
        t0.is_alive.return_value = True
        t1 = MagicMock()
        # worker_1 stops / is not alive
        t1.is_alive.return_value = False
        mock_spawn.side_effect = [t0, t1]

        q0 = MagicMock(spec=mp.Queue)
        q1 = MagicMock(spec=mp.Queue)
        scale_q = MagicMock()
        scale_q.get.side_effect = ["worker_1", Empty]
        scale_q.get_nowait.side_effect = Empty

        self.ipc.worker_queues = {"worker_0": q0, "worker_1": q1}
        self.ipc.scale_queue = scale_q

        pool_runner.run_worker_pool(
            self.ipc,
            self.mock_client,
            self.mock_notification,
            self.mock_retry_config,
        )

        # Only 2 spawns: worker_0 initially, worker_1 on scale_queue. No restart for worker_1.
        self.assertEqual(mock_spawn.call_count, 2)
        mock_logging.log_debug.assert_any_call(
            "Thread worker_1 stopped (idle timeout or finished)"
        )

    @patch("workers.pool_runner.ff_logging")
    @patch("workers.pool_runner._spawn_worker_thread")
    @patch("workers.pool_runner.threading.Event")
    def test_pool_runner_restarts_worker_0_when_dead(
        self, mock_event_cls, mock_spawn, mock_logging
    ):
        """Verify that when worker_0 is not alive, pool runner restarts worker_0 with idle_timeout=None."""
        mock_shutdown_event = MagicMock()
        mock_shutdown_event.is_set.side_effect = [False, False, True]
        mock_event_cls.return_value = mock_shutdown_event

        t0 = MagicMock()
        # worker_0 dies
        t0.is_alive.return_value = False
        t0_replacement = MagicMock()
        t0_replacement.is_alive.return_value = True
        mock_spawn.side_effect = [t0, t0_replacement]

        q0 = MagicMock(spec=mp.Queue)
        q1 = MagicMock(spec=mp.Queue)
        scale_q = MagicMock()
        scale_q.get.side_effect = Empty

        self.ipc.worker_queues = {"worker_0": q0, "worker_1": q1}
        self.ipc.scale_queue = scale_q

        pool_runner.run_worker_pool(
            self.ipc,
            self.mock_client,
            self.mock_notification,
            self.mock_retry_config,
        )

        # worker_0 spawned initially, then restarted
        self.assertEqual(mock_spawn.call_count, 2)
        self.assertEqual(mock_spawn.call_args_list[0][0][0], "worker_0")
        self.assertIsNone(mock_spawn.call_args_list[0][1].get("idle_timeout"))
        self.assertEqual(mock_spawn.call_args_list[1][0][0], "worker_0")
        self.assertIsNone(mock_spawn.call_args_list[1][1].get("idle_timeout"))
        mock_logging.log_failure.assert_called_with(
            "Thread worker_0 died unexpectedly - Restarting..."
        )

    @patch("workers.pool_runner.ff_logging")
    @patch("workers.pool_runner._spawn_worker_thread")
    @patch("workers.pool_runner.threading.Event")
    def test_pool_runner_joins_dying_thread_before_respawn(
        self, mock_event_cls, mock_spawn, mock_logging
    ):
        """Verify dying thread is joined before respawning when re-scale signal is received."""
        mock_shutdown_event = MagicMock()
        mock_shutdown_event.is_set.side_effect = [False, False, True]
        mock_event_cls.return_value = mock_shutdown_event

        t0 = MagicMock()
        t0.is_alive.return_value = True

        dying_thread = MagicMock()
        is_alive_state = True

        def fake_join(timeout=None):
            nonlocal is_alive_state
            is_alive_state = False

        dying_thread.join.side_effect = fake_join
        dying_thread.is_alive.side_effect = lambda: is_alive_state

        replacement_thread = MagicMock()
        replacement_thread.is_alive.return_value = True

        mock_spawn.side_effect = [t0, dying_thread, replacement_thread]

        q0 = MagicMock(spec=mp.Queue)
        q1 = MagicMock(spec=mp.Queue)
        scale_q = MagicMock()
        # Iteration 1 spawns dying_thread, Iteration 2 receives worker_1 again
        scale_q.get.side_effect = ["worker_1", "worker_1", Empty]
        scale_q.get_nowait.side_effect = Empty

        self.ipc.worker_queues = {"worker_0": q0, "worker_1": q1}
        self.ipc.scale_queue = scale_q

        pool_runner.run_worker_pool(
            self.ipc,
            self.mock_client,
            self.mock_notification,
            self.mock_retry_config,
        )

        dying_thread.join.assert_called_once_with(timeout=1.0)
        self.assertEqual(mock_spawn.call_count, 3)
        self.assertEqual(mock_spawn.call_args_list[2][0][0], "worker_1")
        self.assertEqual(
            mock_spawn.call_args_list[2][1].get("idle_timeout"),
            pool_runner.DEFAULT_BURST_IDLE_TIMEOUT,
        )

    @patch("workers.pool_runner.ff_logging")
    @patch("workers.pool_runner._spawn_worker_thread")
    @patch("workers.pool_runner.threading.Event")
    def test_pool_runner_scale_queue_value_error_terminates_cleanly(
        self, mock_event_cls, mock_spawn, mock_logging
    ):
        """Verify ValueError on scale_queue.get() terminates the main loop cleanly."""
        mock_shutdown_event = MagicMock()
        mock_shutdown_event.is_set.return_value = False
        mock_event_cls.return_value = mock_shutdown_event

        t0 = MagicMock()
        t0.is_alive.return_value = True
        mock_spawn.return_value = t0

        q0 = MagicMock(spec=mp.Queue)
        scale_q = MagicMock()
        scale_q.get.side_effect = ValueError("Queue closed")

        self.ipc.worker_queues = {"worker_0": q0}
        self.ipc.scale_queue = scale_q

        pool_runner.run_worker_pool(
            self.ipc,
            self.mock_client,
            self.mock_notification,
            self.mock_retry_config,
        )

        mock_logging.log_debug.assert_any_call("Worker Pool: scale_queue closed")
