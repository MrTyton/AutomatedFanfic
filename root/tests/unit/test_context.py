import unittest
from unittest.mock import MagicMock

from models import config_models
from models.context import WorkerContext
from calibre_integration import calibredb_utils
from notifications import notification_wrapper


class TestWorkerContext(unittest.TestCase):
    def setUp(self):
        self.mock_cdb_info = MagicMock()
        self.mock_client = MagicMock(spec=calibredb_utils.CalibreDBClient)
        self.mock_client.cdb_info = self.mock_cdb_info
        self.mock_notification = MagicMock(
            spec=notification_wrapper.NotificationWrapper
        )
        self.mock_ingress_queue = MagicMock()
        self.mock_waiting_queue = MagicMock()
        self.retry_config = config_models.RetryConfig()
        self.mock_recorder = MagicMock()
        self.active_urls = {"https://archiveofourown.org/works/1": {"status": "queued"}}

    def test_worker_context_bundles_dependencies(self):
        """WorkerContext stores all worker dependencies and exposes cdb_info."""
        ctx = WorkerContext(
            calibre_client=self.mock_client,
            notification_info=self.mock_notification,
            ingress_queue=self.mock_ingress_queue,
            waiting_queue=self.mock_waiting_queue,
            retry_config=self.retry_config,
            history_recorder=self.mock_recorder,
            active_urls=self.active_urls,
        )
        self.assertIs(ctx.calibre_client, self.mock_client)
        self.assertIs(ctx.notification_info, self.mock_notification)
        self.assertIs(ctx.ingress_queue, self.mock_ingress_queue)
        self.assertIs(ctx.waiting_queue, self.mock_waiting_queue)
        self.assertIs(ctx.retry_config, self.retry_config)
        self.assertIs(ctx.history_recorder, self.mock_recorder)
        self.assertIs(ctx.active_urls, self.active_urls)
        self.assertIs(ctx.cdb_info, self.mock_cdb_info)


class TestSharedIPCContextAndProcessLogging(unittest.TestCase):
    def test_shared_ipc_context_picklable_and_defaults(self):
        """SharedIPCContext stores cross-process queues and is picklable."""
        import pickle
        from models.context import SharedIPCContext

        ipc = SharedIPCContext(
            ingress_queue=None,  # type: ignore
            waiting_queue=None,  # type: ignore
            worker_queues={"worker_0": None},  # type: ignore
            active_urls={"url": {"status": "queued"}},
            history_recorder=None,  # type: ignore
            config_store=None,  # type: ignore
        )
        self.assertEqual(ipc.active_urls, {"url": {"status": "queued"}})
        self.assertIsNone(ipc.log_queue)
        self.assertFalse(ipc.verbose)

        restored = pickle.loads(pickle.dumps(ipc))
        self.assertEqual(restored.active_urls, {"url": {"status": "queued"}})
        self.assertFalse(restored.verbose)

    def test_init_process_logging_worker_and_supervisor_modes(self):
        """init_process_logging configures verbose, web_enabled, forward queue, and thread color for non-web processes."""
        from unittest.mock import patch
        from utils import ff_logging

        mock_log_q = MagicMock()
        mock_store = MagicMock()

        with (
            patch.object(ff_logging, "set_verbose") as mock_verbose,
            patch.object(ff_logging, "set_web_enabled") as mock_web,
            patch.object(ff_logging, "set_log_forward_queue") as mock_fwd,
            patch.object(ff_logging, "set_thread_color") as mock_col,
            patch.object(ff_logging, "start_log_drain_thread") as mock_drain,
        ):
            # 1. With log_queue and color (Supervisor with web enabled)
            ff_logging.init_process_logging(
                True,
                color="\033[92m",
                log_queue=mock_log_q,
                config_store=mock_store,
                is_web_server=False,
            )
            mock_verbose.assert_called_once_with(True)
            mock_web.assert_called_once_with(True)
            mock_fwd.assert_called_once_with(mock_log_q)
            mock_col.assert_called_once_with("\033[92m")
            mock_drain.assert_not_called()

            # 2. Without log_queue but with config_store (web disabled)
            mock_verbose.reset_mock()
            mock_web.reset_mock()
            mock_fwd.reset_mock()
            mock_col.reset_mock()
            ff_logging.init_process_logging(
                False,
                log_queue=None,
                config_store=mock_store,
                is_web_server=False,
            )
            mock_verbose.assert_called_once_with(False)
            mock_web.assert_called_once_with(False)
            mock_fwd.assert_called_once_with(None)
            mock_col.assert_not_called()

    def test_init_process_logging_web_server_mode(self):
        """init_process_logging clears forward queue and starts drain thread when is_web_server=True."""
        from unittest.mock import patch
        from utils import ff_logging

        mock_log_q = MagicMock()
        with (
            patch.object(ff_logging, "set_verbose") as mock_verbose,
            patch.object(ff_logging, "set_log_forward_queue") as mock_fwd,
            patch.object(ff_logging, "set_thread_color") as mock_col,
            patch.object(ff_logging, "start_log_drain_thread") as mock_drain,
        ):
            ff_logging.init_process_logging(
                True,
                color="\033[95m",
                log_queue=mock_log_q,
                is_web_server=True,
            )
            mock_verbose.assert_called_once_with(True)
            mock_col.assert_called_once_with("\033[95m")
            mock_fwd.assert_called_once_with(None)
            mock_drain.assert_called_once_with(mock_log_q)

    def test_run_web_server_builds_web_state_from_shared_ipc_context(self):
        """run_web_server initializes logging and constructs WebState from SharedIPCContext."""
        from unittest.mock import patch
        from models.context import SharedIPCContext
        from web import server as web_server

        ipc = SharedIPCContext(
            ingress_queue=MagicMock(),
            waiting_queue=MagicMock(),
            worker_queues={"worker_0": MagicMock()},
            active_urls={"https://ao3.org/works/1": {"status": "queued"}},
            history_recorder=MagicMock(),
            config_store=MagicMock(),
            log_queue=MagicMock(),
            verbose=True,
        )
        mock_cfg = MagicMock()
        mock_cfg.web.host = "127.0.0.1"
        mock_cfg.web.port = 9090
        mock_cfg.web.history_db_path = None
        mock_restart_event = MagicMock()

        with (
            patch("web.server.ff_logging.init_process_logging") as mock_init_log,
            patch("web.server.signal.signal"),
            patch("web.server.create_app") as mock_create_app,
            patch("web.server.uvicorn.Config") as mock_uvicorn_cfg,
            patch("web.server.uvicorn.Server") as mock_uvicorn_srv,
        ):
            web_server.run_web_server(
                ipc,
                app_config=mock_cfg,
                config_path="/config/config.toml",
                web_restart_event=mock_restart_event,
                process_status_callable=None,
            )

        mock_init_log.assert_called_once_with(
            True,
            color="\033[95m",
            log_queue=ipc.log_queue,
            config_store=ipc.config_store,
            is_web_server=True,
        )
        web_state = mock_create_app.call_args.args[0]
        self.assertIs(web_state.active_urls, ipc.active_urls)
        self.assertIs(web_state.ingress_queue, ipc.ingress_queue)
        self.assertIs(web_state.worker_queues, ipc.worker_queues)
        self.assertIs(web_state.waiting_queue, ipc.waiting_queue)
        self.assertIs(web_state.history_recorder, ipc.history_recorder)
        self.assertIs(web_state.config_store, ipc.config_store)
        self.assertIs(web_state.web_restart_event, mock_restart_event)
        self.assertTrue(web_state.verbose)
        mock_uvicorn_cfg.assert_called_once()
        mock_uvicorn_srv.return_value.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
