import unittest
from unittest.mock import MagicMock, patch
import multiprocessing as mp
import subprocess

from workers import pipeline
from models.fanfic_info import FanficInfo
from models import config_models
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
        self.mock_queue = MagicMock(spec=mp.Queue)
        self.retry_config = config_models.RetryConfig()
        self.worker_id = "worker_1"

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
        mock_command.construct_fanficfare_command.side_effect = Exception(
            "Construction Failed"
        )

        pipeline._process_task(
            self.fanfic,
            self.mock_client,
            self.mock_notification,
            self.mock_queue,
            self.retry_config,
            self.worker_id,
        )

        mock_logging.log_failure.assert_called_with(
            "(site) Failed to construct command: Construction Failed"
        )
        mock_handlers.handle_failure.assert_called_once()

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

        error = subprocess.CalledProcessError(1, ["cmd"])
        error.output = b"Bytes Output"
        error.stderr = b"Bytes Error"

        mock_command.construct_fanficfare_command.return_value = ["cmd"]
        mock_command.execute_command.side_effect = error

        pipeline._process_task(
            self.fanfic,
            self.mock_client,
            self.mock_notification,
            self.mock_queue,
            self.retry_config,
            self.worker_id,
        )

        calls = mock_logging.log_debug.call_args_list
        output_logged = any("Bytes Output" in str(c) for c in calls)
        self.assertTrue(output_logged, "Decoded output not logged")

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

        mock_command.construct_fanficfare_command.return_value = ["echo"]
        mock_command.execute_command.return_value = "Output"

        mock_logging.is_verbose.return_value = True

        pipeline._process_task(
            self.fanfic,
            self.mock_client,
            self.mock_notification,
            self.mock_queue,
            self.retry_config,
            self.worker_id,
        )

        mock_common.log_epub_metadata.assert_called_once_with("file.epub", "site")

    @patch("workers.pipeline.ff_logging")
    def test_url_worker_stop(self, mock_logging):
        queue = MagicMock()
        queue.get.return_value = None

        pipeline.url_worker(
            queue,
            self.mock_client,
            self.mock_notification,
            self.mock_queue,
            self.retry_config,
            self.worker_id,
        )

    @patch("workers.pipeline.ff_logging")
    @patch("workers.pipeline.time")
    def test_url_worker_queue_error(self, mock_time, mock_logging):
        """Test queue Exception handling."""
        queue = MagicMock()
        queue.get.side_effect = [Exception("Queue Error"), None, KeyboardInterrupt]

        pipeline.url_worker(
            queue,
            self.mock_client,
            self.mock_notification,
            self.mock_queue,
            self.retry_config,
            self.worker_id,
        )

        mock_logging.log_failure.assert_called_with(
            "Worker worker_1 error waiting: Queue Error"
        )
        mock_time.sleep.assert_called_with(1)


if __name__ == "__main__":
    unittest.main()
