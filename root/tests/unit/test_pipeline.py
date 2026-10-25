from queue import Empty
import unittest
from unittest.mock import MagicMock, patch

from calibre_integration import calibredb_utils
from models import config_models
from models.context import WorkerContext
from models.fanfic_info import FanficInfo
from notifications import notification_wrapper
from workers import pipeline
from workers.command import FanFicFareResult


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
            history_recorder=MagicMock(),
            active_urls={},
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

    @patch("workers.pipeline.system_utils.reclaim_memory")
    @patch("workers.pipeline.ff_logging")
    @patch("workers.pipeline.time.monotonic")
    def test_worker_idle_timeout_terminates_non_permanent_worker(
        self, mock_monotonic, mock_logging, mock_reclaim_memory
    ):
        """Worker with idle_timeout=60.0 exits after staying idle for >= 60.0s."""
        queue = MagicMock()
        queue.get.side_effect = Empty
        # Initial last_active_time = 0.0, intermediate idle check = 30.0, timeout check = 65.0
        mock_monotonic.side_effect = [0.0, 30.0, 65.0]

        pipeline.url_worker(queue, self.ctx, self.worker_id, idle_timeout=60.0)

        self.mock_ingress_queue.put.assert_called_once_with(
            ("WORKER_STOPPED", self.worker_id, None)
        )
        mock_reclaim_memory.assert_called_once()
        mock_logging.log_debug.assert_any_call(
            f"Worker {self.worker_id} reached idle timeout (60.0s) - stopping thread"
        )

    @patch("workers.pipeline.system_utils.reclaim_memory")
    @patch("workers.pipeline.ff_logging")
    @patch("workers.pipeline.time.monotonic")
    def test_worker_permanent_worker_does_not_terminate_on_idle(
        self, mock_monotonic, mock_logging, mock_reclaim_memory
    ):
        """Worker with idle_timeout=None does not exit when idle."""
        queue = MagicMock()
        queue.get.side_effect = [Empty, Empty, None]
        mock_monotonic.side_effect = [0.0, 100.0, 200.0]

        pipeline.url_worker(queue, self.ctx, self.worker_id, idle_timeout=None)

        self.mock_ingress_queue.put.assert_not_called()
        mock_reclaim_memory.assert_not_called()

    @patch("workers.pipeline.handlers.process_fanfic_addition", return_value=True)
    @patch("workers.pipeline.command.execute_fanficfare_direct")
    @patch(
        "workers.pipeline.common.get_path_or_url",
        return_value="http://example.com/story",
    )
    @patch("workers.pipeline.system_utils.temporary_directory")
    @patch("workers.pipeline.system_utils.reclaim_memory")
    @patch("workers.pipeline.ff_logging")
    @patch("workers.pipeline.time.monotonic")
    def test_worker_idle_timeout_resets_after_draining_site(
        self,
        mock_monotonic,
        mock_logging,
        mock_reclaim_memory,
        mock_temp_dir,
        mock_path_or_url,
        mock_fff,
        mock_addition,
    ):
        """Worker resets idle timer when draining a site queue."""
        mock_temp_dir.return_value.__enter__.return_value = "/tmp"
        mock_fff.return_value = FanFicFareResult()

        queue = MagicMock()
        # 1. Receive fanfic task
        # 2. Drain site queue (raises Empty while current_site is "site")
        # 3. Next poll raises Empty (idle check: not timed out yet relative to site drain)
        # 4. Next poll raises Empty (idle check: timed out)
        queue.get.side_effect = [self.fanfic, Empty, Empty, Empty]

        mock_monotonic.side_effect = [
            0.0,  # startup last_active_time
            10.0,  # after task completion
            20.0,  # draining site in Empty handler (last_active_time reset to 20.0)
            70.0,  # idle check: 70 - 20 = 50 < 60 (continues)
            85.0,  # idle check: 85 - 20 = 65 >= 60 (times out)
        ]

        pipeline.url_worker(queue, self.ctx, self.worker_id, idle_timeout=60.0)

        # Ingress queue got WORKER_IDLE for site, then WORKER_STOPPED
        self.mock_ingress_queue.put.assert_any_call(
            ("WORKER_IDLE", self.worker_id, "site")
        )
        self.mock_ingress_queue.put.assert_any_call(
            ("WORKER_STOPPED", self.worker_id, None)
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
            history_recorder=MagicMock(),
            active_urls={},
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
        queue = MagicMock()
        queue.get.side_effect = [Empty, self.fanfic, Empty, None]

        pipeline.url_worker(queue, self.ctx, self.worker_id)

        timeouts = [call.kwargs.get("timeout") for call in queue.get.call_args_list]
        self.assertEqual(timeouts, [2.0, 2.0, 0.05, 2.0])

    @patch("workers.pipeline.time.sleep")
    @patch("workers.pipeline.handlers.process_fanfic_addition", return_value=True)
    @patch("workers.pipeline.command.execute_fanficfare_direct")
    @patch(
        "workers.pipeline.common.get_path_or_url",
        return_value="https://archiveofourown.org/works/1",
    )
    @patch("workers.pipeline.system_utils.temporary_directory")
    @patch("workers.pipeline.ff_logging")
    def test_url_worker_applies_cooldown_sleep_between_failed_task_and_next_same_site_task(
        self,
        mock_logging,
        mock_temp_dir,
        mock_path_or_url,
        mock_fff,
        mock_addition,
        mock_sleep,
    ):
        """When a download fails (bypassing FFF SleepDecorator), worker sleeps FAILURE_COOLDOWN_SECONDS before starting the next task on the same site."""
        mock_temp_dir.return_value.__enter__.return_value = "/tmp"
        fanfic1 = FanficInfo(
            url="https://archiveofourown.org/works/1",
            site="archiveofourown",
            title="Story 1",
        )
        fanfic2 = FanficInfo(
            url="https://archiveofourown.org/works/2",
            site="archiveofourown",
            title="Story 2",
        )
        fanfic3 = FanficInfo(
            url="https://archiveofourown.org/works/3",
            site="archiveofourown",
            title="Story 3",
        )
        mock_fff.side_effect = [
            FanFicFareResult(failure_messages=["HTTP Error 525"]),
            FanFicFareResult(),
            FanFicFareResult(),
        ]

        queue = MagicMock()
        queue.get.side_effect = [fanfic1, fanfic2, fanfic3, None]

        pipeline.url_worker(queue, self.ctx, self.worker_id)

        # Cooldown sleep must be called once (between failed fanfic1 and fanfic2),
        # and NOT between successful fanfic2 and fanfic3.
        mock_sleep.assert_called_once_with(pipeline.FAILURE_COOLDOWN_SECONDS)

    @patch("workers.pipeline.time.sleep")
    @patch("workers.pipeline.command.execute_fanficfare_direct")
    @patch(
        "workers.pipeline.common.get_path_or_url",
        return_value="https://archiveofourown.org/works/1",
    )
    @patch("workers.pipeline.system_utils.temporary_directory")
    @patch("workers.pipeline.ff_logging")
    def test_url_worker_does_not_sleep_cooldown_when_queue_drains_after_failure(
        self,
        mock_logging,
        mock_temp_dir,
        mock_path_or_url,
        mock_fff,
        mock_sleep,
    ):
        """When a task fails and the site queue is empty, worker releases the site lock without a pointless cooldown sleep."""
        mock_temp_dir.return_value.__enter__.return_value = "/tmp"
        fanfic1 = FanficInfo(
            url="https://archiveofourown.org/works/1",
            site="archiveofourown",
            title="Story 1",
        )
        mock_fff.return_value = FanFicFareResult(failure_messages=["HTTP Error 525"])

        queue = MagicMock()
        queue.get.side_effect = [fanfic1, Empty, None]

        pipeline.url_worker(queue, self.ctx, self.worker_id)

        mock_sleep.assert_not_called()

    @patch("workers.pipeline.time.sleep")
    @patch("workers.pipeline._process_task")
    @patch("workers.pipeline.ff_logging")
    def test_url_worker_applies_cooldown_sleep_after_unhandled_task_exception(
        self,
        mock_logging,
        mock_process_task,
        mock_sleep,
    ):
        """When _process_task raises an unhandled exception, worker cools down before the next task on the same site."""
        fanfic1 = FanficInfo(
            url="https://archiveofourown.org/works/1",
            site="archiveofourown",
            title="Story 1",
        )
        fanfic2 = FanficInfo(
            url="https://archiveofourown.org/works/2",
            site="archiveofourown",
            title="Story 2",
        )
        mock_process_task.side_effect = [RuntimeError("unexpected crash"), True]

        queue = MagicMock()
        queue.get.side_effect = [fanfic1, fanfic2, None]

        pipeline.url_worker(queue, self.ctx, self.worker_id)

        mock_sleep.assert_called_once_with(pipeline.FAILURE_COOLDOWN_SECONDS)


@patch("workers.pipeline.ff_logging")
@patch("workers.pipeline.system_utils")
@patch("workers.pipeline.common")
@patch("workers.pipeline.handlers")
@patch("workers.pipeline.command")
class TestUpdateOnlyMode(unittest.TestCase):
    """`calibre.update_only` drops email-sourced URLs that are not in Calibre."""

    def setUp(self):
        self.fanfic = FanficInfo(
            url="http://example.com/story", site="site", title="Test Story"
        )
        self.mock_client = MagicMock(spec=calibredb_utils.CalibreDBClient)
        self.mock_client.cdb_info = MagicMock()
        self.mock_client.cdb_info.update_method = "update"
        self.history_recorder = MagicMock()
        self.ctx = WorkerContext(
            calibre_client=self.mock_client,
            notification_info=MagicMock(spec=notification_wrapper.NotificationWrapper),
            ingress_queue=MagicMock(),
            waiting_queue=MagicMock(),
            retry_config=config_models.RetryConfig(),
            history_recorder=self.history_recorder,
            active_urls={},
        )

    def _arrange(self, mock_command, mock_common, mock_sys, path_or_url):
        mock_sys.temporary_directory.return_value.__enter__.return_value = "/tmp"
        mock_common.get_path_or_url.return_value = path_or_url
        mock_common.extract_title_from_epub_path.return_value = "Test Story"
        mock_command.execute_fanficfare_direct.return_value = FanFicFareResult()

    def test_email_url_not_in_library_is_dropped(
        self, mock_command, mock_handlers, mock_common, mock_sys, mock_logging
    ):
        self.mock_client.cdb_info.update_only = True
        self.fanfic.from_email = True
        self._arrange(mock_command, mock_common, mock_sys, self.fanfic.url)

        result = pipeline._process_task(self.fanfic, self.ctx)

        self.assertTrue(result)
        mock_command.execute_fanficfare_direct.assert_not_called()
        mock_handlers.process_fanfic_addition.assert_not_called()
        mock_handlers.handle_failure.assert_not_called()
        self.history_recorder.record_download_abandoned.assert_called_once()
        _, kwargs = self.history_recorder.record_download_abandoned.call_args
        self.assertEqual(kwargs["site"], "site")
        self.assertIn("update_only", kwargs["error_message"])

    def test_email_url_in_library_is_updated(
        self, mock_command, mock_handlers, mock_common, mock_sys, mock_logging
    ):
        self.mock_client.cdb_info.update_only = True
        self.fanfic.from_email = True
        self._arrange(mock_command, mock_common, mock_sys, "/tmp/Test Story.epub")

        pipeline._process_task(self.fanfic, self.ctx)

        mock_command.execute_fanficfare_direct.assert_called_once()
        self.history_recorder.record_download_abandoned.assert_not_called()

    def test_manual_url_not_in_library_is_downloaded(
        self, mock_command, mock_handlers, mock_common, mock_sys, mock_logging
    ):
        self.mock_client.cdb_info.update_only = True
        self.fanfic.from_email = False
        self._arrange(mock_command, mock_common, mock_sys, self.fanfic.url)

        pipeline._process_task(self.fanfic, self.ctx)

        mock_command.execute_fanficfare_direct.assert_called_once()
        self.history_recorder.record_download_abandoned.assert_not_called()

    def test_email_url_downloaded_when_update_only_disabled(
        self, mock_command, mock_handlers, mock_common, mock_sys, mock_logging
    ):
        self.mock_client.cdb_info.update_only = False
        self.fanfic.from_email = True
        self._arrange(mock_command, mock_common, mock_sys, self.fanfic.url)

        pipeline._process_task(self.fanfic, self.ctx)

        mock_command.execute_fanficfare_direct.assert_called_once()
        self.history_recorder.record_download_abandoned.assert_not_called()


if __name__ == "__main__":
    unittest.main()
