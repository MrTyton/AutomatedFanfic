import unittest
from unittest.mock import MagicMock, patch

from workers import pipeline
from models.fanfic_info import FanficInfo
from models import config_models
from models.context import WorkerContext
from calibre_integration import calibredb_utils
from notifications import notification_wrapper


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.fanfic = FanficInfo(
            url="http://example.com/story", site="site", title="Test Story"
        )
        self.mock_client = MagicMock(spec=calibredb_utils.CalibreDBClient)
        self.mock_client.cdb_info = MagicMock()
        self.mock_notification = MagicMock(
            spec=notification_wrapper.NotificationWrapper
        )
        self.mock_ingress_queue = MagicMock()
        self.mock_waiting_queue = MagicMock()
        self.retry_config = config_models.RetryConfig()
        self.worker_id = "worker_1"
        self.ctx = WorkerContext(
            calibre_client=self.mock_client,
            notification_info=self.mock_notification,
            ingress_queue=self.mock_ingress_queue,
            waiting_queue=self.mock_waiting_queue,
            retry_config=self.retry_config,
        )

    @patch("workers.pipeline.command")
    @patch("workers.pipeline.handlers")
    @patch("workers.pipeline.common")
    @patch("workers.pipeline.system_utils")
    @patch("workers.pipeline.ff_logging")
    def test_process_task_command_construction_error(
        self, mock_logging, mock_sys, mock_common, mock_handlers, mock_command
    ):
        mock_sys.temporary_directory.return_value.__enter__.return_value = "/tmp"
        mock_common.get_path_or_url.return_value = "http://example.com/story"
        from workers.command import FanFicFareResult

        mock_command.FanFicFareResult = FanFicFareResult
        mock_command.execute_fanficfare_direct.return_value = FanFicFareResult(
            failure_messages=["Construction Failed"]
        )

        pipeline._process_task(self.fanfic, self.ctx)

        mock_handlers.handle_failure.assert_called_once_with(
            self.fanfic,
            self.ctx,
            error_message="Construction Failed",
        )

    @patch("workers.pipeline.command")
    @patch("workers.pipeline.handlers")
    @patch("workers.pipeline.common")
    @patch("workers.pipeline.system_utils")
    @patch("workers.pipeline.ff_logging")
    def test_process_task_execution_error_decoding_bytes(
        self, mock_logging, mock_sys, mock_common, mock_handlers, mock_command
    ):
        mock_sys.temporary_directory.return_value.__enter__.return_value = "/tmp"
        mock_common.get_path_or_url.return_value = "http://example.com/story"

        from workers.command import FanFicFareResult

        mock_command.FanFicFareResult = FanFicFareResult
        mock_command.execute_fanficfare_direct.return_value = FanFicFareResult(
            failure_messages=["Bytes Output"]
        )

        pipeline._process_task(self.fanfic, self.ctx)

        mock_handlers.handle_failure.assert_called_once()
        _, kwargs = mock_handlers.handle_failure.call_args
        self.assertIn("Bytes Output", kwargs["error_message"])

    @patch("workers.pipeline.command")
    @patch("workers.pipeline.handlers")
    @patch("workers.pipeline.common")
    @patch("workers.pipeline.system_utils")
    @patch("workers.pipeline.ff_logging")
    def test_verbose_logging_metadata(
        self, mock_logging, mock_sys, mock_common, mock_handlers, mock_command
    ):
        mock_sys.temporary_directory.return_value.__enter__.return_value = "/tmp"
        mock_common.get_path_or_url.return_value = "file.epub"
        mock_common.extract_title_from_epub_path.return_value = "file.epub"

        from workers.command import FanFicFareResult

        mock_command.FanFicFareResult = FanFicFareResult
        mock_command.execute_fanficfare_direct.return_value = FanFicFareResult()

        mock_logging.is_verbose.return_value = True

        pipeline._process_task(self.fanfic, self.ctx)

        mock_common.log_epub_metadata.assert_called_once_with("file.epub", "site")

    @patch("workers.pipeline.ff_logging")
    def test_url_worker_stop(self, mock_logging):
        queue = MagicMock()
        queue.get.return_value = None

        pipeline.url_worker(queue, self.ctx, self.worker_id)

    @patch("workers.pipeline.ff_logging")
    @patch("workers.pipeline.time")
    def test_url_worker_queue_error(self, mock_time, mock_logging):
        """Test queue Exception handling."""
        queue = MagicMock()
        queue.get.side_effect = [Exception("Queue Error"), None, KeyboardInterrupt]

        pipeline.url_worker(queue, self.ctx, self.worker_id)

        mock_logging.log_failure.assert_called_with(
            "Worker worker_1 error waiting: Queue Error"
        )
        mock_time.sleep.assert_called_with(1)

    @patch("workers.pipeline.ff_logging")
    def test_signal_worker_idle_helper_behavior(self, mock_logging):
        """_signal_worker_idle sends WORKER_IDLE when current_site is set and skips when None."""
        # None site -> no-op
        pipeline._signal_worker_idle(self.mock_ingress_queue, "worker_1", None)
        self.mock_ingress_queue.put.assert_not_called()

        # Non-None site -> emits WORKER_IDLE and clears thread site
        pipeline._signal_worker_idle(self.mock_ingress_queue, "worker_1", "ao3")
        self.mock_ingress_queue.put.assert_called_once_with(
            ("WORKER_IDLE", "worker_1", "ao3")
        )
        mock_logging.set_thread_site.assert_called_once_with(None)

        # Suppress errors when queue raises on shutdown
        self.mock_ingress_queue.put.side_effect = OSError("Queue closed")
        pipeline._signal_worker_idle(
            self.mock_ingress_queue, "worker_1", "ao3", suppress_errors=True
        )


class TestPipelineEdgeCases(unittest.TestCase):
    """Test edge cases and error paths in pipeline."""

    def setUp(self):
        self.fanfic = FanficInfo(
            url="http://example.com/story", site="site", title="Test Story"
        )
        self.mock_client = MagicMock(spec=calibredb_utils.CalibreDBClient)
        self.mock_client.cdb_info = MagicMock()
        self.mock_notification = MagicMock(
            spec=notification_wrapper.NotificationWrapper
        )
        self.mock_ingress_queue = MagicMock()
        self.mock_waiting_queue = MagicMock()
        self.retry_config = config_models.RetryConfig()
        self.worker_id = "worker_1"
        self.ctx = WorkerContext(
            calibre_client=self.mock_client,
            notification_info=self.mock_notification,
            ingress_queue=self.mock_ingress_queue,
            waiting_queue=self.mock_waiting_queue,
            retry_config=self.retry_config,
        )

    @patch("workers.pipeline.ff_logging")
    @patch("workers.pipeline.time")
    def test_url_worker_queue_closed_error(self, mock_time, mock_logging):
        """Test handling of ValueError when queue is closed."""
        queue = MagicMock()
        queue.get.side_effect = [ValueError("Queue closed"), None]

        pipeline.url_worker(queue, self.ctx, self.worker_id)

        # Should log warning about queue closed
        calls = [str(call) for call in mock_logging.log.call_args_list]
        self.assertTrue(any("queue closed" in call.lower() for call in calls))

    @patch("workers.pipeline.ff_logging")
    def test_url_worker_keyboard_interrupt(self, mock_logging):
        """Test handling of KeyboardInterrupt in worker loop."""
        queue = MagicMock()
        queue.get.side_effect = KeyboardInterrupt

        pipeline.url_worker(queue, self.ctx, self.worker_id)

        # Should log interruption
        calls = [str(call) for call in mock_logging.log.call_args_list]
        self.assertTrue(any("interrupted" in call.lower() for call in calls))

    @patch("workers.pipeline.command")
    @patch("workers.pipeline.handlers")
    @patch("workers.pipeline.common")
    @patch("workers.pipeline.system_utils")
    @patch("workers.pipeline.ff_logging")
    def test_process_task_force_with_update_no_force(
        self, mock_logging, mock_sys, mock_common, mock_handlers, mock_command
    ):
        """Test force update requested but update_no_force configured."""
        self.fanfic.behavior = "force"
        self.mock_client.cdb_info.update_method = "update_no_force"

        mock_sys.temporary_directory.return_value.__enter__.return_value = "/tmp"
        mock_common.get_path_or_url.return_value = "http://example.com/story"
        from workers.command import FanFicFareResult

        mock_command.FanFicFareResult = FanFicFareResult

        pipeline._process_task(self.fanfic, self.ctx)

        # Should trigger failure handler
        mock_handlers.handle_failure.assert_called_once()

        # Should log failure
        mock_logging.log_failure.assert_called()
        mock_command.execute_fanficfare_direct.assert_not_called()

    @patch("workers.pipeline.ff_logging")
    def test_url_worker_invalid_worker_id_format(self, mock_logging):
        """Test worker with invalid ID format (for color assignment)."""
        queue = MagicMock()
        queue.get.return_value = None

        pipeline.url_worker(queue, self.ctx, "invalid_worker_id_format")

        self.assertTrue(mock_logging.log.called)

    @patch("workers.pipeline._process_task")
    @patch("workers.pipeline.ff_logging")
    def test_url_worker_adaptive_queue_timeout(self, mock_logging, mock_process_task):
        """Worker uses 2.0s timeout when idle and 0.05s timeout while holding a site lock."""
        from queue import Empty

        queue = MagicMock()
        queue.get.side_effect = [Empty, self.fanfic, Empty, None]

        pipeline.url_worker(queue, self.ctx, self.worker_id)

        timeouts = [call.kwargs.get("timeout") for call in queue.get.call_args_list]
        self.assertEqual(timeouts, [2.0, 2.0, 0.05, 2.0])


if __name__ == "__main__":
    unittest.main()
