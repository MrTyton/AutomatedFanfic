import unittest
from unittest.mock import patch, MagicMock
from url_ingester import email_watcher, EmailInfo
from url_worker import url_worker
from fanfic_info import FanficInfo
from config_models import RetryConfig
import retry_types


class TestDuplicatePrevention(unittest.TestCase):
    def setUp(self):
        self.active_urls = {}
        self.queue = MagicMock()
        self.notification_info = MagicMock()
        self.email_info = MagicMock(spec=EmailInfo)
        self.email_info.disabled_sites = []
        self.email_info.sleep_time = 0.1
        self.processor_queues = {"fanfiction": MagicMock(), "other": MagicMock()}
        self.url_parsers = {}

    @patch("url_ingester.time.sleep")
    @patch("url_ingester.regex_parsing.generate_FanficInfo_from_url")
    @patch("url_ingester.ff_logging.log")
    def test_email_watcher_adds_to_active_urls(
        self, mock_log, mock_generate, mock_sleep
    ):
        # Setup
        url = "https://www.fanfiction.net/s/12345/1/"
        self.email_info.get_urls.side_effect = [[url], KeyboardInterrupt()]

        fanfic = FanficInfo(site="fanfiction", url=url)
        mock_generate.return_value = fanfic

        # Execute
        try:
            email_watcher(
                self.email_info,
                self.notification_info,
                self.processor_queues,
                self.url_parsers,
                self.active_urls,
            )
        except KeyboardInterrupt:
            pass

        # Verify
        self.assertIn(url, self.active_urls)
        self.processor_queues["fanfiction"].put.assert_called_with(fanfic)

    @patch("url_ingester.time.sleep")
    @patch("url_ingester.regex_parsing.generate_FanficInfo_from_url")
    @patch("url_ingester.ff_logging.log")
    def test_email_watcher_skips_active_url(self, mock_log, mock_generate, mock_sleep):
        # Setup
        url = "https://www.fanfiction.net/s/12345/1/"
        self.active_urls[url] = True

        self.email_info.get_urls.side_effect = [[url], KeyboardInterrupt()]

        fanfic = FanficInfo(site="fanfiction", url=url)
        mock_generate.return_value = fanfic

        # Execute
        try:
            email_watcher(
                self.email_info,
                self.notification_info,
                self.processor_queues,
                self.url_parsers,
                self.active_urls,
            )
        except KeyboardInterrupt:
            pass

        # Verify
        self.processor_queues["fanfiction"].put.assert_not_called()
        # Should log a warning
        mock_log.assert_any_call(
            f"Skipping {url} - already in queue or processing", "WARNING"
        )

    @patch("url_worker.system_utils.copy_configs_to_temp_dir")
    @patch("url_worker.system_utils.temporary_directory")
    @patch("url_worker.get_path_or_url")
    @patch("url_worker.construct_fanficfare_command")
    @patch("url_worker.execute_command")
    @patch("url_worker.process_fanfic_addition")
    @patch("url_worker.sleep")
    @patch("url_worker.ff_logging")
    def test_url_worker_removes_from_active_urls_on_success(
        self,
        mock_logging,
        mock_sleep,
        mock_process,
        mock_exec,
        mock_construct,
        mock_get_path,
        mock_temp_dir,
        mock_copy_configs,
    ):
        # Setup
        url = "https://www.fanfiction.net/s/12345/1/"
        fanfic = FanficInfo(site="fanfiction", url=url)
        self.active_urls[url] = True

        # Queue returns fanfic then raises KeyboardInterrupt to exit loop
        self.queue.get.side_effect = [fanfic, KeyboardInterrupt]
        self.queue.empty.return_value = False

        # Mocks for successful execution
        mock_temp_dir.return_value.__enter__.return_value = "/tmp"
        mock_get_path.return_value = url
        mock_construct.return_value = "fanficfare -u " + url
        mock_exec.return_value = "Download successful"

        cdb = MagicMock()
        retry_config = MagicMock(spec=RetryConfig)
        retry_config.max_normal_retries = 3
        waiting_queue = MagicMock()

        # Execute
        try:
            url_worker(
                self.queue,
                cdb,
                self.notification_info,
                waiting_queue,
                retry_config,
                self.active_urls,
            )
        except KeyboardInterrupt:
            pass

        # Verify
        self.assertNotIn(url, self.active_urls)

    @patch("url_worker.system_utils.copy_configs_to_temp_dir")
    @patch("url_worker.system_utils.temporary_directory")
    @patch("url_worker.get_path_or_url")
    @patch("url_worker.handle_failure")
    @patch("url_worker.sleep")
    @patch("url_worker.ff_logging")
    @patch("url_worker.execute_command")
    def test_url_worker_keeps_active_on_retry(
        self,
        mock_exec,
        mock_logging,
        mock_sleep,
        mock_handle_failure,
        mock_get_path,
        mock_temp_dir,
        mock_copy_configs,
    ):
        # Setup
        url = "https://www.fanfiction.net/s/12345/1/"
        fanfic = FanficInfo(site="fanfiction", url=url)
        self.active_urls[url] = True

        self.queue.get.side_effect = [fanfic, KeyboardInterrupt]
        self.queue.empty.return_value = False

        # Mocks
        mock_temp_dir.return_value.__enter__.return_value = "/tmp"
        mock_get_path.return_value = url

        # Simulate exception in execution (inside inner try block)
        mock_exec.side_effect = Exception("Download failed")

        # Mock handle_failure to set retry decision
        def side_effect_handle_failure(fanfic, *args):
            fanfic.retry_decision = MagicMock()
            fanfic.retry_decision.action = retry_types.FailureAction.RETRY

        mock_handle_failure.side_effect = side_effect_handle_failure

        cdb = MagicMock()
        retry_config = MagicMock(spec=RetryConfig)
        retry_config.max_normal_retries = 3
        waiting_queue = MagicMock()

        # Execute
        try:
            url_worker(
                self.queue,
                cdb,
                self.notification_info,
                waiting_queue,
                retry_config,
                self.active_urls,
            )
        except KeyboardInterrupt:
            pass

        # Verify
        self.assertIn(url, self.active_urls)

    @patch("url_worker.system_utils.copy_configs_to_temp_dir")
    @patch("url_worker.system_utils.temporary_directory")
    @patch("url_worker.get_path_or_url")
    @patch("url_worker.handle_failure")
    @patch("url_worker.sleep")
    @patch("url_worker.ff_logging")
    @patch("url_worker.execute_command")
    def test_url_worker_removes_active_on_abandon(
        self,
        mock_exec,
        mock_logging,
        mock_sleep,
        mock_handle_failure,
        mock_get_path,
        mock_temp_dir,
        mock_copy_configs,
    ):
        # Setup
        url = "https://www.fanfiction.net/s/12345/1/"
        fanfic = FanficInfo(site="fanfiction", url=url)
        self.active_urls[url] = True

        self.queue.get.side_effect = [fanfic, KeyboardInterrupt]
        self.queue.empty.return_value = False

        # Mocks
        mock_temp_dir.return_value.__enter__.return_value = "/tmp"
        mock_get_path.return_value = url

        # Simulate exception in execution
        mock_exec.side_effect = Exception("Download failed")

        # Mock handle_failure to set abandon decision
        def side_effect_handle_failure(fanfic, *args):
            fanfic.retry_decision = MagicMock()
            fanfic.retry_decision.action = retry_types.FailureAction.ABANDON

        mock_handle_failure.side_effect = side_effect_handle_failure

        cdb = MagicMock()
        retry_config = MagicMock(spec=RetryConfig)
        retry_config.max_normal_retries = 3
        waiting_queue = MagicMock()

        # Execute
        try:
            url_worker(
                self.queue,
                cdb,
                self.notification_info,
                waiting_queue,
                retry_config,
                self.active_urls,
            )
        except KeyboardInterrupt:
            pass

        # Verify
        self.assertNotIn(url, self.active_urls)


if __name__ == "__main__":
    unittest.main()
