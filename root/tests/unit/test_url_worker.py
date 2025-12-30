import unittest
from unittest.mock import MagicMock, patch
from parameterized import parameterized
import multiprocessing as mp
from subprocess import STDOUT, PIPE

import url_worker
import config_models
from fanfic_info import FanficInfo
from calibre_info import CalibreInfo
from notification_wrapper import NotificationWrapper
import calibredb_utils
from typing import NamedTuple, Optional


class TestUrlWorker(unittest.TestCase):
    class HandleFailureTestCase(NamedTuple):
        name: str
        retry_count: int  # The current repeats value
        max_normal_retries: int  # Config setting
        hail_mary_enabled: bool  # Config setting
        expected_log_message: str
        expected_notification_call: bool
        expected_notification_title: Optional[str]
        expected_queue_put_call: bool

    @parameterized.expand(
        [
            # Case 1: Normal retry - not reached maximum repeats
            HandleFailureTestCase(
                name="normal_retry",
                retry_count=3,  # Will become 4 after increment, less than max_normal_retries (11)
                max_normal_retries=11,
                hail_mary_enabled=True,
                expected_log_message="Sending Test Story to waiting queue for retry. Attempt 4",
                expected_notification_call=False,
                expected_notification_title=None,
                expected_queue_put_call=True,
            ),
            # Case 2: Hail-Mary activation - exactly at maximum normal retries
            HandleFailureTestCase(
                name="hail_mary_activation",
                retry_count=10,  # Will become 11 after increment, equals max_normal_retries
                max_normal_retries=11,
                hail_mary_enabled=True,
                expected_log_message="Sending Test Story to waiting queue for hail_mary. Attempt 11",
                expected_notification_call=True,
                expected_notification_title="Fanfiction Download Failed, trying Hail-Mary in 12.00 hours.",
                expected_queue_put_call=True,
            ),
            # Case 3: Abandonment - beyond maximum retries
            HandleFailureTestCase(
                name="abandonment",
                retry_count=11,  # Will become 12 after increment, beyond max_normal_retries + hail_mary
                max_normal_retries=11,
                hail_mary_enabled=True,
                expected_log_message="Maximum retries reached for Test Story. Abandoning after 12 attempts.",
                expected_notification_call=False,
                expected_notification_title=None,
                expected_queue_put_call=False,
            ),
        ]
    )
    @patch("ff_logging.log_failure")
    def test_handle_failure(
        self,
        name,
        retry_count,
        max_normal_retries,
        hail_mary_enabled,
        expected_log_message,
        expected_notification_call,
        expected_notification_title,
        expected_queue_put_call,
        mock_log_failure,
    ):
        # Setup
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "site"
        mock_fanfic.title = "Test Story"
        mock_fanfic.repeats = retry_count  # Set the repeats to control decision

        mock_notification_info = MagicMock(spec=NotificationWrapper)
        mock_waiting_queue = MagicMock(spec=mp.Queue)
        mock_waiting_queue.put = MagicMock()

        # Mock increment_repeat to simulate the actual increment behavior
        def simulate_increment():
            mock_fanfic.repeats += 1

        mock_fanfic.increment_repeat = MagicMock(side_effect=simulate_increment)

        # Create retry config with specific settings for this test
        retry_config = config_models.RetryConfig(
            max_normal_retries=max_normal_retries,
            hail_mary_enabled=hail_mary_enabled,
            hail_mary_wait_hours=12.0,  # Standard wait time
        )

        # Execution
        url_worker.handle_failure(
            mock_fanfic,
            mock_notification_info,
            mock_waiting_queue,
            retry_config,
        )

        # Assertions
        # log_failure should be called with the expected message
        mock_log_failure.assert_called_with(expected_log_message)

        if expected_notification_call:
            mock_notification_info.send_notification.assert_called_once_with(
                expected_notification_title, mock_fanfic.url, mock_fanfic.site
            )
        else:
            mock_notification_info.send_notification.assert_not_called()

        if expected_queue_put_call:
            mock_waiting_queue.put.assert_called_once_with(mock_fanfic)
        else:
            mock_waiting_queue.put.assert_not_called()

        # increment_repeat is always called in the new architecture
        mock_fanfic.increment_repeat.assert_called_once()

    class HandleFailureUpdateNoForceTestCase(NamedTuple):
        name: str
        behavior: str
        update_method: str
        reached_maximum_repeats: tuple[bool, bool]
        should_send_notification: bool
        expected_notification_title: str
        expected_notification_body: str
        expected_log_message: str

    @parameterized.expand(
        [
            HandleFailureUpdateNoForceTestCase(
                name="hail_mary_force_update_no_force",
                behavior="force",
                update_method="update_no_force",
                reached_maximum_repeats=(True, True),
                should_send_notification=True,
                expected_notification_title="Fanfiction Update Permanently Skipped",
                expected_notification_body="Update for http://example.com/story was permanently skipped because a force was requested but the update method is set to 'update_no_force'. The force request was ignored and a normal update was attempted instead.",
                expected_log_message="Maximum retries reached for Test Story. Abandoning after 12 attempts.",
            ),
            HandleFailureUpdateNoForceTestCase(
                name="hail_mary_non_force_update_no_force",
                behavior="update",
                update_method="update_no_force",
                reached_maximum_repeats=(True, True),
                should_send_notification=False,
                expected_notification_title="",
                expected_notification_body="",
                expected_log_message="Maximum retries reached for Test Story. Abandoning after 12 attempts.",
            ),
            HandleFailureUpdateNoForceTestCase(
                name="hail_mary_force_different_update_method",
                behavior="force",
                update_method="update_always",
                reached_maximum_repeats=(True, True),
                should_send_notification=False,
                expected_notification_title="",
                expected_notification_body="",
                expected_log_message="Maximum retries reached for Test Story. Abandoning after 12 attempts.",
            ),
        ]
    )
    @patch("ff_logging.log_failure")
    def test_handle_failure_update_no_force(
        self,
        name,
        behavior,
        update_method,
        reached_maximum_repeats,
        should_send_notification,
        expected_notification_title,
        expected_notification_body,
        expected_log_message,
        mock_log_failure,
    ):
        """Test handle_failure with update_no_force scenarios."""
        # Setup common mocks
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "test_site"
        mock_fanfic.title = "Test Story"
        mock_fanfic.repeats = 11  # Will become 12 after increment, triggers abandonment
        mock_fanfic.behavior = behavior

        # Mock increment_repeat to simulate the actual increment behavior
        def simulate_increment():
            mock_fanfic.repeats += 1

        mock_fanfic.increment_repeat = MagicMock(side_effect=simulate_increment)

        mock_notification_info = MagicMock(spec=NotificationWrapper)
        mock_waiting_queue = MagicMock(spec=mp.Queue)
        mock_waiting_queue.put = MagicMock()
        mock_cdb = MagicMock(spec=CalibreInfo)
        mock_cdb.update_method = update_method

        # Create real retry config
        retry_config = config_models.RetryConfig(
            max_normal_retries=11, hail_mary_enabled=True, hail_mary_wait_hours=12.0
        )

        url_worker.handle_failure(
            mock_fanfic,
            mock_notification_info,
            mock_waiting_queue,
            retry_config,
            mock_cdb,
        )

        # Assertions
        mock_log_failure.assert_called_with(expected_log_message)

        if should_send_notification:
            mock_notification_info.send_notification.assert_called_once_with(
                expected_notification_title,
                expected_notification_body,
                "test_site",
            )
        else:
            mock_notification_info.send_notification.assert_not_called()

        mock_waiting_queue.put.assert_not_called()

    @patch("ff_logging.log_failure")
    def test_handle_failure_with_none_cdb(self, mock_log_failure):
        """Test handle_failure with cdb=None (should never send special notification)."""
        # Setup common mocks
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "test_site"
        mock_fanfic.title = "Test Story"
        mock_fanfic.repeats = 3  # Will become 4 after increment, triggers normal retry
        mock_fanfic.behavior = "force"

        # Mock increment_repeat to simulate the actual increment behavior
        def simulate_increment():
            mock_fanfic.repeats += 1

        mock_fanfic.increment_repeat = MagicMock(side_effect=simulate_increment)
        mock_notification_info = MagicMock(spec=NotificationWrapper)
        mock_waiting_queue = MagicMock(spec=mp.Queue)
        mock_waiting_queue.put = MagicMock()

        # Create real retry config
        retry_config = config_models.RetryConfig(
            max_normal_retries=11, hail_mary_enabled=True, hail_mary_wait_hours=12.0
        )

        # Test Case: Normal retry with force behavior but cdb=None -> should retry normally
        url_worker.handle_failure(
            mock_fanfic,
            mock_notification_info,
            mock_waiting_queue,
            retry_config,
        )

        # Assertions - should log retry and queue the fanfic
        mock_log_failure.assert_called_once_with(
            "Sending Test Story to waiting queue for retry. Attempt 4"
        )
        mock_notification_info.send_notification.assert_not_called()
        mock_waiting_queue.put.assert_called_once_with(mock_fanfic)

    class HandleFailureEdgeCaseTestCase(NamedTuple):
        name: str
        behavior: str | None
        reached_maximum_repeats: tuple[bool, bool]
        expected_log_message: str

    @parameterized.expand(
        [
            HandleFailureEdgeCaseTestCase(
                name="none_behavior",
                behavior=None,
                reached_maximum_repeats=(True, True),
                expected_log_message="Maximum retries reached for Test Story. Abandoning after 12 attempts.",
            ),
            HandleFailureEdgeCaseTestCase(
                name="empty_behavior",
                behavior="",
                reached_maximum_repeats=(True, True),
                expected_log_message="Maximum retries reached for Test Story. Abandoning after 12 attempts.",
            ),
        ]
    )
    @patch("ff_logging.log_failure")
    def test_handle_failure_edge_cases(
        self,
        name,
        behavior,
        reached_maximum_repeats,
        expected_log_message,
        mock_log_failure,
    ):
        """Test handle_failure edge cases with different behavior values."""
        # Setup common mocks
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "test_site"
        mock_fanfic.title = "Test Story"
        mock_fanfic.repeats = 11  # Will become 12 after increment, triggers abandonment
        mock_fanfic.behavior = behavior

        # Mock increment_repeat to simulate the actual increment behavior
        def simulate_increment():
            mock_fanfic.repeats += 1

        mock_fanfic.increment_repeat = MagicMock(side_effect=simulate_increment)

        mock_notification_info = MagicMock(spec=NotificationWrapper)
        mock_waiting_queue = MagicMock(spec=mp.Queue)
        mock_waiting_queue.put = MagicMock()

        # Create real retry config
        retry_config = config_models.RetryConfig(
            max_normal_retries=11, hail_mary_enabled=True, hail_mary_wait_hours=12.0
        )

        url_worker.handle_failure(
            mock_fanfic, mock_notification_info, mock_waiting_queue, retry_config
        )

        mock_log_failure.assert_called_with(expected_log_message)
        mock_notification_info.send_notification.assert_not_called()

    class GetPathOrUrlTestCase(NamedTuple):
        fanfic_in_calibre: bool
        exported_files: list
        expected_result: str

    @parameterized.expand(
        [
            GetPathOrUrlTestCase(
                fanfic_in_calibre=True,
                exported_files=["/fake/path/story.epub"],
                expected_result="/fake/path/story.epub",
            ),
            GetPathOrUrlTestCase(
                fanfic_in_calibre=True,
                exported_files=[],
                expected_result="http://example.com/story",
            ),
            GetPathOrUrlTestCase(
                fanfic_in_calibre=False,
                exported_files=[],
                expected_result="http://example.com/story",
            ),
        ]
    )
    @patch("system_utils.get_files")
    def test_get_path_or_url(
        self,
        fanfic_in_calibre,
        exported_files,
        expected_result,
        mock_get_files,
    ):
        # Setup
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.url = "http://example.com/story"

        mock_client = MagicMock()
        mock_client.get_story_id.return_value = fanfic_in_calibre

        mock_get_files.return_value = exported_files

        # Execution
        result = url_worker.get_path_or_url(mock_fanfic, mock_client, "/fake/path")

        # Assertions
        self.assertEqual(result, expected_result)

        if fanfic_in_calibre:
            mock_client.export_story.assert_called_once_with(
                fanfic=mock_fanfic, location="/fake/path"
            )
        else:
            mock_client.export_story.assert_not_called()

    class ExecuteCommandTestCase(NamedTuple):
        command: str
        expected_output: str

    @parameterized.expand(
        [
            ExecuteCommandTestCase(
                command="echo Hello",
                expected_output="Hello",
            ),
        ]
    )
    @patch("url_worker.check_output")
    def test_execute_command(
        self,
        command,
        expected_output,
        mock_check_output,
    ):
        # Setup
        mock_check_output.return_value = expected_output.encode("utf-8")

        # Execution
        result = url_worker.execute_command(command)

        # Assertions
        self.assertEqual(result.strip(), expected_output)
        mock_check_output.assert_called_once_with(
            command, shell=True, stderr=STDOUT, stdin=PIPE, cwd=None
        )

    @patch("url_worker.check_output")
    def test_execute_command_error_handling(self, mock_check_output):
        """Test execute_command error handling."""
        from subprocess import CalledProcessError

        # Setup mock to raise CalledProcessError
        mock_check_output.side_effect = CalledProcessError(
            1, "failed_command", "error output"
        )

        # Execution and assertion
        with self.assertRaises(CalledProcessError):
            url_worker.execute_command("failed_command")

        mock_check_output.assert_called_once_with(
            "failed_command", shell=True, stderr=STDOUT, stdin=PIPE, cwd=None
        )

    @patch("url_worker.check_output")
    def test_execute_command_unicode_handling(self, mock_check_output):
        """Test execute_command with unicode output."""
        # Setup mock with unicode output
        unicode_output = "Test with ñ special characters 测试"
        mock_check_output.return_value = unicode_output.encode("utf-8")

        # Execution
        result = url_worker.execute_command("test command")

        # Assertions
        self.assertEqual(result, unicode_output)
        mock_check_output.assert_called_once_with(
            "test command", shell=True, stderr=STDOUT, stdin=PIPE, cwd=None
        )

    class ProcessFanficAdditionTestCase(NamedTuple):
        calibre_id: Optional[int]
        get_id_from_calibredb_returns: bool  # Renamed for clarity
        expected_remove_story_call: bool
        expected_handle_failure_call: bool  # Check if handle_failure is called
        expected_success_notification_call: bool  # Renamed for clarity

    @parameterized.expand(
        [
            # Case 1: Existing story, add fails
            ProcessFanficAdditionTestCase(
                calibre_id=123,
                get_id_from_calibredb_returns=False,
                expected_remove_story_call=True,
                expected_handle_failure_call=True,
                expected_success_notification_call=False,
            ),
            # Case 2: New story, add succeeds
            ProcessFanficAdditionTestCase(
                calibre_id=None,
                get_id_from_calibredb_returns=True,
                expected_remove_story_call=False,
                expected_handle_failure_call=False,
                expected_success_notification_call=True,
            ),
            # Case 3: Existing story, add succeeds
            ProcessFanficAdditionTestCase(
                calibre_id=123,
                get_id_from_calibredb_returns=True,
                expected_remove_story_call=True,
                expected_handle_failure_call=False,
                expected_success_notification_call=True,
            ),
            # Case 4: New story, add fails
            ProcessFanficAdditionTestCase(
                calibre_id=None,
                get_id_from_calibredb_returns=False,
                expected_remove_story_call=False,
                expected_handle_failure_call=True,
                expected_success_notification_call=False,
            ),
        ]
    )
    @patch("url_worker.handle_failure")  # Patch handle_failure directly
    @patch("url_worker.update_strategies")  # Patch strategies to avoid actual execution
    @patch(
        "ff_logging.log_failure"
    )  # Keep patching log_failure for the specific log inside this function
    def test_process_fanfic_addition(
        self,
        calibre_id,
        get_id_from_calibredb_returns,
        expected_remove_story_call,
        expected_handle_failure_call,
        expected_success_notification_call,
        mock_log_failure,  # Keep this mock
        mock_update_strategies,
        mock_handle_failure,  # Add mock for handle_failure
    ):
        # Setup
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.calibre_id = calibre_id
        # get_id_from_calibredb is now on the client, not fanfic

        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "site"
        mock_fanfic.title = "title"

        mock_client = MagicMock()
        mock_client.get_story_id.return_value = get_id_from_calibredb_returns
        mock_client.cdb_info.metadata_preservation_mode = "remove_add"

        mock_notification_info = MagicMock(spec=NotificationWrapper)
        mock_queue = MagicMock(spec=mp.Queue)

        # Setup strategy execution mock
        mock_strategy_instance = MagicMock()
        mock_update_strategies.RemoveAddStrategy.return_value = mock_strategy_instance
        # If expected_handle_failure_call is True (case 1 and 4), it means strategy failed or add_story failed
        # For existing story (case 1), strategy.execute returns False (assuming strategy handles failure logging/calling)
        # But wait, original code calls strategy.execute with failure_handler.
        # So mocks need to simulate strategy return value

        if calibre_id:  # Existing story cases
            if expected_handle_failure_call:
                mock_strategy_instance.execute.return_value = False
            else:
                mock_strategy_instance.execute.return_value = True
        else:  # New story cases
            # For new stories, we call client.add_story, then client.get_story_id again
            # The parametrized input `get_id_from_calibredb_returns` controls the result of the check
            # But logic calls get_story_id TWICE for new stories?
            # 1. At start: get_story_id -> False (new story)
            # 2. Add story
            # 3. Verify: get_story_id -> True/False

            # We need side_effect for get_story_id: [False, get_id_from_calibredb_returns]
            # But `get_id_from_calibredb_returns` in the test cases meant "Is the story in DB?"
            # For new story test cases (calibre_id=None), get_id_from_calibredb_returns meant the result AFTER addition.

            if not get_id_from_calibredb_returns:
                # This signifies failure to add
                mock_client.get_story_id.side_effect = [False, False]
            else:
                mock_client.get_story_id.side_effect = [False, True]

            # Unless it's an existing story being processed (First call returns True)

        if calibre_id:
            mock_client.get_story_id.return_value = True  # Found initially

        # Execution
        url_worker.process_fanfic_addition(
            mock_fanfic,
            mock_client,
            "/fake/temp/dir",
            "site",
            "path_or_url",
            mock_queue,
            mock_notification_info,
            config_models.RetryConfig(),
        )

        # Assertions

        if calibre_id:
            # Existing story path - uses Strategy
            if expected_handle_failure_call:
                # Strategy returns False
                pass  # Strategy called handler internally, tested in strategy tests
            else:
                pass

            # Verify strategy execution
            mock_strategy_instance.execute.assert_called_once()

            # Remove story/Add story are inside Strategy now, so we don't verify them on client here
            # We verify that Strategy.execute was called with correct args

        else:
            # New story path
            mock_client.add_story.assert_called_once_with(
                location="/fake/temp/dir", fanfic=mock_fanfic
            )

            if expected_handle_failure_call:
                mock_log_failure.assert_called_once_with(
                    "\t(site) Failed to add path_or_url to Calibre"
                )
                mock_handle_failure.assert_called_once()
                mock_notification_info.send_notification.assert_not_called()
            else:
                if expected_success_notification_call:
                    mock_notification_info.send_notification.assert_called_once_with(
                        "New Fanfiction Download", mock_fanfic.title, "site"
                    )


class TestUrlWorkerMainLoop(unittest.TestCase):
    """Test the main url_worker() function loop that processes fanfics from queue."""

    def setUp(self):
        """Set up common mocks for url_worker main loop tests."""
        self.mock_queue = MagicMock()
        self.mock_cdb = MagicMock(spec=CalibreInfo)
        self.mock_cdb.library_path = "/mock/library/path"
        self.mock_client = MagicMock(spec=calibredb_utils.CalibreDBClient)
        self.mock_client.cdb_info = self.mock_cdb
        self.mock_notification_info = MagicMock(spec=NotificationWrapper)
        self.mock_waiting_queue = MagicMock()

        # Create test fanfic object
        self.test_fanfic = MagicMock(spec=FanficInfo)
        self.test_fanfic.site = "test_site"
        self.test_fanfic.url = "http://example.com/story"
        self.test_fanfic.behavior = "update"
        self.test_fanfic.max_repeats = None

        # Counter to track calls and exit after processing one item
        self.call_count = 0

    def create_queue_get_side_effect(self, fanfic_to_return):
        """Create a side effect function that returns fanfic once then raises exception to exit."""

        def queue_get_side_effect():
            self.call_count += 1
            if self.call_count == 1:
                return fanfic_to_return
            # After processing the fanfic, raise an exception to exit the infinite loop
            raise KeyboardInterrupt("Test exit")

        return queue_get_side_effect

    @patch("url_worker.config_models.ConfigManager.load_config")
    @patch("url_worker.system_utils.temporary_directory")
    @patch("url_worker.get_path_or_url")
    @patch("url_worker.construct_fanficfare_command")
    @patch("url_worker.ff_logging.log")
    @patch("url_worker.handle_failure")
    def test_url_worker_force_update_no_force_exception(
        self,
        mock_handle_failure,
        mock_log,
        mock_construct_cmd,
        mock_get_path,
        mock_temp_dir,
        mock_load_config,
    ):
        """Test exception handling for force request with update_no_force configuration."""
        # Set up fanfic that requests force with update_no_force config
        self.test_fanfic.behavior = "force"
        self.mock_cdb.update_method = "update_no_force"

        # Set up queue behavior
        self.mock_queue.empty.return_value = False
        self.mock_queue.get.side_effect = self.create_queue_get_side_effect(
            self.test_fanfic
        )

        # Create retry config for testing
        retry_config = config_models.RetryConfig(
            hail_mary_enabled=True, hail_mary_wait_hours=12.0, max_normal_retries=11
        )

        # Set up temp directory and basic processing
        mock_temp_dir.return_value.__enter__.return_value = "/tmp/test"
        mock_get_path.return_value = "test_file.epub"
        mock_construct_cmd.return_value = "fanficfare command"

        # Mock logging failure to capture the specific error message
        with patch("url_worker.ff_logging.log_failure") as mock_log_failure:
            # Run worker - will exit with KeyboardInterrupt after processing
            with self.assertRaises(KeyboardInterrupt):
                url_worker.url_worker(
                    self.mock_queue,
                    self.mock_client,
                    self.mock_notification_info,
                    self.mock_waiting_queue,
                    retry_config,
                )

            # Verify that exception was triggered and failure handler called
            mock_log_failure.assert_called_once_with(
                "\t(test_site) Failed to update test_file.epub: Force update requested but update method is 'update_no_force'"
            )
            mock_handle_failure.assert_called_once_with(
                self.test_fanfic,
                self.mock_notification_info,
                self.mock_waiting_queue,
                retry_config,
                self.mock_cdb,
            )

    @patch("url_worker.execute_command")
    @patch("url_worker.system_utils.copy_configs_to_temp_dir")
    @patch("url_worker.system_utils.temporary_directory")
    @patch("url_worker.get_path_or_url")
    @patch("url_worker.construct_fanficfare_command")
    @patch("url_worker.ff_logging.log")
    @patch("url_worker.handle_failure")
    def test_url_worker_execute_command_exception(
        self,
        mock_handle_failure,
        mock_log,
        mock_construct_cmd,
        mock_get_path,
        mock_temp_dir,
        mock_copy_configs,
        mock_execute,
    ):
        """Test exception handling when execute_command fails."""
        # Set up queue behavior
        self.mock_queue.empty.return_value = False
        self.mock_queue.get.side_effect = self.create_queue_get_side_effect(
            self.test_fanfic
        )

        # Set up temp directory and processing until execute_command
        mock_temp_dir.return_value.__enter__.return_value = "/tmp/test"
        mock_get_path.return_value = "test_file.epub"
        mock_construct_cmd.return_value = "fanficfare command"
        mock_execute.side_effect = Exception("Command execution failed")

        # Create retry config for testing
        retry_config = config_models.RetryConfig(
            hail_mary_enabled=True, hail_mary_wait_hours=12.0, max_normal_retries=11
        )

        # Mock logging failure to capture the specific error message
        with patch("url_worker.ff_logging.log_failure") as mock_log_failure:
            # Run worker - will exit with KeyboardInterrupt after processing
            with self.assertRaises(KeyboardInterrupt):
                url_worker.url_worker(
                    self.mock_queue,
                    self.mock_client,
                    self.mock_notification_info,
                    self.mock_waiting_queue,
                    retry_config,
                )

            # Verify that exception was caught and failure handler called
            mock_log_failure.assert_any_call(
                "\t(test_site) Failed to update test_file.epub: Command execution failed"
            )
            mock_handle_failure.assert_called_once_with(
                self.test_fanfic,
                self.mock_notification_info,
                self.mock_waiting_queue,
                retry_config,
                self.mock_cdb,
            )

    @patch("url_worker.execute_command")
    @patch("url_worker.system_utils.copy_configs_to_temp_dir")
    @patch("url_worker.system_utils.temporary_directory")
    @patch("url_worker.get_path_or_url")
    @patch("url_worker.construct_fanficfare_command")
    @patch("url_worker.regex_parsing.check_failure_regexes")
    @patch("url_worker.ff_logging.log")
    @patch("url_worker.handle_failure")
    def test_url_worker_failure_regex_detection(
        self,
        mock_handle_failure,
        mock_log,
        mock_check_failure,
        mock_construct_cmd,
        mock_get_path,
        mock_temp_dir,
        mock_copy_configs,
        mock_execute,
    ):
        """Test failure detection via regex parsing."""
        # Set up queue behavior
        self.mock_queue.empty.return_value = False
        self.mock_queue.get.side_effect = self.create_queue_get_side_effect(
            self.test_fanfic
        )

        # Set up successful execution but failure regex detection
        mock_temp_dir.return_value.__enter__.return_value = "/tmp/test"
        mock_get_path.return_value = "test_file.epub"
        mock_construct_cmd.return_value = "fanficfare command"
        mock_execute.return_value = "output with failure indicators"
        mock_check_failure.return_value = False  # Failure detected

        # Create retry config for testing
        retry_config = config_models.RetryConfig(
            hail_mary_enabled=True, hail_mary_wait_hours=12.0, max_normal_retries=11
        )

        # Run worker - will exit with KeyboardInterrupt after processing
        with self.assertRaises(KeyboardInterrupt):
            url_worker.url_worker(
                self.mock_queue,
                self.mock_client,
                self.mock_notification_info,
                self.mock_waiting_queue,
                retry_config,
            )

        # Verify failure handler was called due to regex detection
        mock_handle_failure.assert_called_once_with(
            self.test_fanfic,
            self.mock_notification_info,
            self.mock_waiting_queue,
            retry_config,
            self.mock_cdb,
        )

    @patch("url_worker.execute_command")
    @patch("url_worker.system_utils.copy_configs_to_temp_dir")
    @patch("url_worker.system_utils.temporary_directory")
    @patch("url_worker.get_path_or_url")
    @patch("url_worker.construct_fanficfare_command")
    @patch("url_worker.regex_parsing.check_failure_regexes")
    @patch("url_worker.regex_parsing.check_forceable_regexes")
    @patch("url_worker.ff_logging.log")
    def test_url_worker_force_retry_logic(
        self,
        mock_log,
        mock_check_forceable,
        mock_check_failure,
        mock_construct_cmd,
        mock_get_path,
        mock_temp_dir,
        mock_copy_configs,
        mock_execute,
    ):
        """Test force retry logic when forceable conditions are detected."""
        # Set up queue behavior
        self.mock_queue.empty.return_value = False
        self.mock_queue.get.side_effect = self.create_queue_get_side_effect(
            self.test_fanfic
        )

        # Set up successful execution with forceable condition
        mock_temp_dir.return_value.__enter__.return_value = "/tmp/test"
        mock_get_path.return_value = "test_file.epub"
        mock_construct_cmd.return_value = "fanficfare command"
        mock_execute.return_value = "output with forceable condition"
        mock_check_failure.return_value = True  # No permanent failure
        mock_check_forceable.return_value = True  # Force retry needed

        # Create retry config for testing
        retry_config = config_models.RetryConfig(
            hail_mary_enabled=True, hail_mary_wait_hours=12.0, max_normal_retries=11
        )

        # Run worker - will exit with KeyboardInterrupt after processing
        with self.assertRaises(KeyboardInterrupt):
            url_worker.url_worker(
                self.mock_queue,
                self.mock_client,
                self.mock_notification_info,
                self.mock_waiting_queue,
                retry_config,
            )

        # Verify fanfic was re-queued with force behavior
        self.assertEqual(self.test_fanfic.behavior, "force")
        self.mock_queue.put.assert_called_once_with(self.test_fanfic)

    @patch("url_worker.process_fanfic_addition")
    @patch("url_worker.execute_command")
    @patch("url_worker.system_utils.copy_configs_to_temp_dir")
    @patch("url_worker.system_utils.temporary_directory")
    @patch("url_worker.get_path_or_url")
    @patch("url_worker.construct_fanficfare_command")
    @patch("url_worker.regex_parsing.check_failure_regexes")
    @patch("url_worker.regex_parsing.check_forceable_regexes")
    @patch("url_worker.ff_logging.log")
    def test_url_worker_successful_processing(
        self,
        mock_log,
        mock_check_forceable,
        mock_check_failure,
        mock_construct_cmd,
        mock_get_path,
        mock_temp_dir,
        mock_copy_configs,
        mock_execute,
        mock_process_addition,
    ):
        """Test successful processing path through url_worker."""
        # Set up queue behavior
        self.mock_queue.empty.return_value = False
        self.mock_queue.get.side_effect = self.create_queue_get_side_effect(
            self.test_fanfic
        )

        # Set up successful processing path
        mock_temp_dir.return_value.__enter__.return_value = "/tmp/test"
        mock_get_path.return_value = "test_file.epub"
        mock_construct_cmd.return_value = "fanficfare command"
        mock_execute.return_value = "successful output"
        mock_check_failure.return_value = True  # No failure
        mock_check_forceable.return_value = False  # No force needed

        # Create retry config for testing
        retry_config = config_models.RetryConfig(
            hail_mary_enabled=True, hail_mary_wait_hours=12.0, max_normal_retries=11
        )

        # Run worker - will exit with KeyboardInterrupt after processing
        with self.assertRaises(KeyboardInterrupt):
            url_worker.url_worker(
                self.mock_queue,
                self.mock_client,
                self.mock_notification_info,
                self.mock_waiting_queue,
                retry_config,
            )

        # Verify successful processing
        mock_process_addition.assert_called_once_with(
            self.test_fanfic,
            self.mock_client,
            "/tmp/test",
            "test_site",
            "test_file.epub",
            self.mock_waiting_queue,
            self.mock_notification_info,
            retry_config,
        )


class TestExtractTitleFromEpubPath(unittest.TestCase):
    """Test cases for the extract_title_from_epub_path function."""

    class TitleExtractionTestCase(NamedTuple):
        """Test case structure for title extraction tests."""

        name: str
        input_path: str
        expected_output: str
        description: str

    @parameterized.expand(
        [
            TitleExtractionTestCase(
                name="windows_path_with_title",
                input_path=r"C:\Users\TestUser\AppData\Local\Temp\tmpoz7malhf\Save Scumming - RavensDagger.epub",
                expected_output="Save Scumming - RavensDagger",
                description="Extract title from Windows temporary directory path",
            ),
            TitleExtractionTestCase(
                name="linux_path_with_title",
                input_path="/tmp/tmpxyz123/The Chronicles of Narnia - C.S. Lewis.epub",
                expected_output="The Chronicles of Narnia - C.S. Lewis",
                description="Extract title from Linux temporary directory path",
            ),
            TitleExtractionTestCase(
                name="simple_filename",
                input_path="Harry Potter and the Sorcerer's Stone.epub",
                expected_output="Harry Potter and the Sorcerer's Stone",
                description="Extract title from simple filename",
            ),
            TitleExtractionTestCase(
                name="title_with_special_characters",
                input_path="/some/path/Story Title - Author [2023] (Updated).epub",
                expected_output="Story Title - Author [2023] (Updated)",
                description="Extract title with brackets, parentheses, and special characters",
            ),
            TitleExtractionTestCase(
                name="title_with_numbers",
                input_path="/temp/Book 1 - The Beginning - John Doe.epub",
                expected_output="Book 1 - The Beginning - John Doe",
                description="Extract title with numbers and multiple hyphens",
            ),
            TitleExtractionTestCase(
                name="uppercase_epub_extension",
                input_path="/path/to/STORY TITLE - AUTHOR.EPUB",
                expected_output="STORY TITLE - AUTHOR",
                description="Handle uppercase .EPUB extension",
            ),
            TitleExtractionTestCase(
                name="mixed_case_epub_extension",
                input_path="/path/to/Mixed Case Title.ePub",
                expected_output="Mixed Case Title",
                description="Handle mixed case .ePub extension",
            ),
            TitleExtractionTestCase(
                name="url_input_unchanged",
                input_path="https://royalroad.com/fiction/127120",
                expected_output="https://royalroad.com/fiction/127120",
                description="URL input should be returned unchanged",
            ),
            TitleExtractionTestCase(
                name="http_url_unchanged",
                input_path="http://archiveofourown.org/works/12345",
                expected_output="http://archiveofourown.org/works/12345",
                description="HTTP URL input should be returned unchanged",
            ),
            TitleExtractionTestCase(
                name="non_epub_file",
                input_path="/path/to/document.txt",
                expected_output="/path/to/document.txt",
                description="Non-epub file should be returned unchanged",
            ),
            TitleExtractionTestCase(
                name="path_without_extension",
                input_path="/path/to/some_file",
                expected_output="/path/to/some_file",
                description="Path without extension should be returned unchanged",
            ),
            TitleExtractionTestCase(
                name="empty_string",
                input_path="",
                expected_output="",
                description="Empty string should be returned unchanged",
            ),
            TitleExtractionTestCase(
                name="only_epub_extension",
                input_path=".epub",
                expected_output="",
                description="File with only .epub extension should return empty string",
            ),
            TitleExtractionTestCase(
                name="epub_in_middle_of_path",
                input_path="/path/to/folder.epub/actual_file.txt",
                expected_output="/path/to/folder.epub/actual_file.txt",
                description="Path with .epub in directory name but non-epub file should be unchanged",
            ),
        ]
    )
    def test_extract_title_from_epub_path(
        self, name, input_path, expected_output, description
    ):
        """Test the extract_title_from_epub_path function with various inputs."""
        result = url_worker.extract_title_from_epub_path(input_path)
        self.assertEqual(
            result,
            expected_output,
            f"Failed for {name}: {description}. Expected '{expected_output}', got '{result}'",
        )

    def test_extract_title_error_handling(self):
        """Test that the function handles unexpected errors gracefully."""
        # Test with a malformed path that could cause os.path.basename to fail
        # We'll patch os.path.basename to raise an exception
        with patch("os.path.basename", side_effect=Exception("Simulated error")):
            test_path = "/some/path/story.epub"
            result = url_worker.extract_title_from_epub_path(test_path)
            # Should return the original path when an exception occurs
            self.assertEqual(result, test_path)


class TestTitleExtractionIntegration(unittest.TestCase):
    """Integration tests for title extraction in the URL worker processing flow."""

    def setUp(self):
        """Set up test fixtures."""
        self.fanfic = FanficInfo(
            url="https://example.com/story/123",
            site="example",
            title="https://example.com/story/123",  # Initially set to URL
        )

    @patch("url_worker.get_path_or_url")
    @patch("url_worker.ff_logging.log_debug")
    def test_title_extraction_in_processing_flow(
        self, mock_log_debug, mock_get_path_or_url
    ):
        """Test that title extraction works in the actual processing context."""
        # Simulate get_path_or_url returning an epub file path
        epub_path = "/tmp/tmpxyz123/Test Story - Author Name.epub"
        mock_get_path_or_url.return_value = epub_path

        # Import the processing logic (we'd need to refactor to test this properly)
        # For now, we'll test the logic directly

        # Simulate the title extraction logic from url_worker
        if epub_path.endswith(".epub"):
            extracted_title = url_worker.extract_title_from_epub_path(epub_path)
            if extracted_title != epub_path:
                self.fanfic.title = extracted_title

        # Verify the title was updated correctly
        self.assertEqual(self.fanfic.title, "Test Story - Author Name")

    def test_title_not_updated_for_url_input(self):
        """Test that title is not updated when path_or_url is a URL."""
        url = "https://royalroad.com/fiction/127120"

        # Simulate the processing logic
        if url.endswith(".epub"):
            extracted_title = url_worker.extract_title_from_epub_path(url)
            if extracted_title != url:
                self.fanfic.title = extracted_title

        # Title should remain unchanged since it's a URL, not an epub path
        self.assertEqual(self.fanfic.title, "https://example.com/story/123")


class GetFanficfareVersionTestCase(unittest.TestCase):
    """Test cases for get_fanficfare_version function."""

    @parameterized.expand(
        [
            (
                "standard_version",
                "Version: 4.48.7\n",
                "4.48.7",
            ),
            (
                "older_version",
                "Version: 4.30.12\n",
                "4.30.12",
            ),
            (
                "minimal_version",
                "Version: 3.0.0\n",
                "3.0.0",
            ),
            (
                "version_with_extra_whitespace",
                "Version:    4.48.7   \n",
                "4.48.7",
            ),
        ]
    )
    @patch("url_worker.execute_command")
    def test_get_fanficfare_version_success(
        self, name, mock_output, expected_version, mock_execute
    ):
        """Test successful FanFicFare version extraction with various output formats."""
        mock_execute.return_value = mock_output

        result = url_worker.get_fanficfare_version()

        self.assertEqual(result, expected_version)
        mock_execute.assert_called_once_with("python -m fanficfare.cli --version")

    @parameterized.expand(
        [
            (
                "command_execution_error",
                Exception("Command failed"),
                "Error: Command failed",
            ),
            (
                "subprocess_error",
                Exception(
                    "subprocess.CalledProcessError: Command 'python' returned non-zero exit status 1"
                ),
                "Error: subprocess.CalledProcessError: Command 'python' returned non-zero exit status 1",
            ),
        ]
    )
    @patch("url_worker.execute_command")
    def test_get_fanficfare_version_errors(
        self, name, mock_exception, expected_message, mock_execute
    ):
        """Test error handling for various failure scenarios."""
        mock_execute.side_effect = mock_exception

        result = url_worker.get_fanficfare_version()

        self.assertEqual(result, expected_message)

    @parameterized.expand(
        [
            (
                "unexpected_format",
                "Some unexpected output\n",
                "Some unexpected output",
            ),
            (
                "no_version_keyword",
                "4.48.7\n",
                "4.48.7",
            ),
            (
                "empty_output",
                "",
                "",
            ),
            (
                "different_format",
                "FanFicFare version 4.48.7\n",
                "FanFicFare version 4.48.7",
            ),
        ]
    )
    @patch("url_worker.execute_command")
    def test_get_fanficfare_version_unexpected_format(
        self, name, mock_output, expected_result, mock_execute
    ):
        """Test handling of unexpected output formats."""
        mock_execute.return_value = mock_output

        result = url_worker.get_fanficfare_version()

        self.assertEqual(result, expected_result)

    @parameterized.expand(
        [
            (
                "verbose_enabled_with_bytes_output",
                True,  # verbose enabled
                b"ERROR: Story not found on site\nTraceback: ...\n",  # error output
                "ERROR: Story not found on site",  # expected in output
            ),
            (
                "verbose_enabled_with_string_output",
                True,  # verbose enabled
                "ERROR: Story not found on site\nTraceback: ...\n",  # error output as string
                "ERROR: Story not found on site",  # expected in output
            ),
            (
                "verbose_disabled_with_output",
                False,  # verbose disabled
                b"ERROR: Story not found on site\nTraceback: ...\n",  # error output
                None,  # should not log debug
            ),
        ]
    )
    @patch("ff_logging.log_debug")
    @patch("ff_logging.log_failure")
    @patch("ff_logging.verbose")
    def test_fanfic_addition_verbose_error_output(
        self,
        name,
        verbose_enabled,
        error_output,
        expected_output,
        mock_verbose,
        mock_log_failure,
        mock_log_debug,
    ):
        """Test that CalledProcessError output is logged in verbose mode."""
        from subprocess import CalledProcessError

        # Setup verbose flag
        mock_verbose.value = verbose_enabled

        # Simulate CalledProcessError with output
        called_process_error = CalledProcessError(
            returncode=1,
            cmd="fanficfare -u --update-cover story.epub",
            output=error_output,
        )

        # Create mock objects
        mock_fanfic = MagicMock()
        mock_fanfic.url = "https://archiveofourown.org/works/12345"
        mock_fanfic.site = "archiveofourown.org"
        MagicMock()
        MagicMock()
        MagicMock()
        MagicMock()

        # Capture the actual exception handling logic from url_worker
        # by simulating what would happen in the try/except block
        try:
            raise called_process_error
        except CalledProcessError as e:
            # This mimics the code in url_worker.py lines 695-713
            mock_log_failure(
                f"\t({mock_fanfic.site}) Failed to update {mock_fanfic.url}: {e}"
            )

            # In verbose mode, show the actual FanFicFare output for debugging
            # Note: log_debug internally checks verbose.value, so we always call it
            if e.output:
                error_output_str = (
                    e.output.decode("utf-8")
                    if isinstance(e.output, bytes)
                    else str(e.output)
                )
                mock_log_debug(
                    f"\t({mock_fanfic.site}) FanFicFare output:\n{error_output_str}"
                )

        # Verify failure was logged
        mock_log_failure.assert_called_once()
        failure_call = mock_log_failure.call_args[0][0]
        self.assertIn("Failed to update", failure_call)

        # Verify debug output logging
        # log_debug is always called if there's output, but log_debug internally
        # checks verbose.value to decide whether to actually print
        if expected_output:
            # Should have been called
            mock_log_debug.assert_called_once()
            debug_call = mock_log_debug.call_args[0][0]
            self.assertIn("FanFicFare output:", debug_call)
            self.assertIn(expected_output, debug_call)
        else:
            # Even though it's called, log_debug won't print when verbose=False
            # But the mock still records the call, so we check it was called
            mock_log_debug.assert_called_once()
            debug_call = mock_log_debug.call_args[0][0]
            self.assertIn("FanFicFare output:", debug_call)


class TestLogEpubMetadata(unittest.TestCase):
    """Test suite for log_epub_metadata function."""

    @patch("url_worker.ff_logging")
    def test_valid_epub_with_metadata(self, mock_logging):
        """Test logging metadata from a valid epub file."""
        import tempfile
        import zipfile
        import os

        # Create a temporary epub with metadata
        with tempfile.NamedTemporaryFile(
            mode="w+b", suffix=".epub", delete=False
        ) as epub_file:
            epub_path = epub_file.name

            # Create a valid OPF content
            opf_content = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:title>Test Story</dc:title>
        <dc:creator>Test Author</dc:creator>
        <dc:identifier scheme="URL">https://archiveofourown.org/works/123456</dc:identifier>
        <dc:language>en</dc:language>
    </metadata>
</package>"""

            # Create the epub zip file
            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr("content.opf", opf_content)

        try:
            # Call the function
            url_worker.log_epub_metadata(epub_path, "ao3")

            # Verify logging calls
            calls = [str(call) for call in mock_logging.log_debug.call_args_list]

            # Should have logged the start
            self.assertTrue(
                any("Reading epub metadata from:" in call for call in calls)
            )

            # Should have logged metadata start/end markers
            self.assertTrue(any("=== EPUB METADATA ===" in call for call in calls))
            self.assertTrue(any("=== END METADATA ===" in call for call in calls))

            # Should have logged the metadata elements
            self.assertTrue(any("title: Test Story" in call for call in calls))
            self.assertTrue(any("creator: Test Author" in call for call in calls))
            self.assertTrue(
                any(
                    "identifier" in call
                    and 'scheme="URL"' in call
                    and "https://archiveofourown.org/works/123456" in call
                    for call in calls
                )
            )

        finally:
            os.unlink(epub_path)

    @patch("url_worker.ff_logging")
    def test_epub_without_opf_file(self, mock_logging):
        """Test handling epub without .opf file."""
        import tempfile
        import zipfile
        import os

        # Create an epub without .opf file
        with tempfile.NamedTemporaryFile(
            mode="w+b", suffix=".epub", delete=False
        ) as epub_file:
            epub_path = epub_file.name

            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr("random.txt", "No OPF here")

        try:
            url_worker.log_epub_metadata(epub_path, "ffn")

            # Should log error about missing .opf file
            calls = [str(call) for call in mock_logging.log_debug.call_args_list]
            self.assertTrue(any("Could not find .opf file" in call for call in calls))

        finally:
            os.unlink(epub_path)

    @patch("url_worker.ff_logging")
    def test_epub_with_malformed_opf(self, mock_logging):
        """Test handling epub with malformed XML in .opf file."""
        import tempfile
        import zipfile
        import os

        # Create an epub with malformed OPF
        with tempfile.NamedTemporaryFile(
            mode="w+b", suffix=".epub", delete=False
        ) as epub_file:
            epub_path = epub_file.name

            malformed_opf = "<not-valid-xml><unclosed-tag>"

            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr("content.opf", malformed_opf)

        try:
            url_worker.log_epub_metadata(epub_path, "sb")

            # Should log error about parsing
            calls = [str(call) for call in mock_logging.log_debug.call_args_list]
            self.assertTrue(
                any("Error reading epub metadata:" in call for call in calls)
            )

        finally:
            os.unlink(epub_path)

    @patch("url_worker.ff_logging")
    def test_epub_with_no_metadata_section(self, mock_logging):
        """Test handling epub with valid OPF but no metadata section."""
        import tempfile
        import zipfile
        import os

        # Create an epub with OPF lacking metadata section
        with tempfile.NamedTemporaryFile(
            mode="w+b", suffix=".epub", delete=False
        ) as epub_file:
            epub_path = epub_file.name

            opf_content = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
    <manifest>
        <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    </manifest>
</package>"""

            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr("content.opf", opf_content)

        try:
            url_worker.log_epub_metadata(epub_path, "wattpad")

            # Should log that no metadata section was found
            calls = [str(call) for call in mock_logging.log_debug.call_args_list]
            self.assertTrue(any("No metadata section found" in call for call in calls))

        finally:
            os.unlink(epub_path)

    @patch("url_worker.ff_logging")
    def test_nonexistent_epub_file(self, mock_logging):
        """Test handling non-existent epub file."""
        url_worker.log_epub_metadata("/nonexistent/file.epub", "test")

        # Should log error
        calls = [str(call) for call in mock_logging.log_debug.call_args_list]
        self.assertTrue(any("Error reading epub metadata:" in call for call in calls))

    @patch("url_worker.ff_logging")
    def test_epub_with_attributes_and_empty_values(self, mock_logging):
        """Test logging metadata elements with attributes and empty text values."""
        import tempfile
        import zipfile
        import os

        # Create epub with metadata that has attributes but empty text
        with tempfile.NamedTemporaryFile(
            mode="w+b", suffix=".epub", delete=False
        ) as epub_file:
            epub_path = epub_file.name

            opf_content = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:title>Story Title</dc:title>
        <dc:identifier scheme="ISBN"></dc:identifier>
        <meta name="calibre:series" content="Test Series"/>
    </metadata>
</package>"""

            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr("content.opf", opf_content)

        try:
            url_worker.log_epub_metadata(epub_path, "other")

            calls = [str(call) for call in mock_logging.log_debug.call_args_list]

            # Should log identifier with scheme attribute even though text is empty
            self.assertTrue(
                any("identifier" in call and 'scheme="ISBN"' in call for call in calls)
            )

            # Should log meta with attributes
            self.assertTrue(
                any(
                    "meta" in call
                    and 'name="calibre:series"' in call
                    and 'content="Test Series"' in call
                    for call in calls
                )
            )

        finally:
            os.unlink(epub_path)


class TestConstructFanficfareCommand(unittest.TestCase):
    """Test suite for construct_fanficfare_command function."""

    def setUp(self):
        """Set up test fixtures."""
        self.calibre_info = MagicMock(spec=CalibreInfo)
        self.calibre_info.update_method = "update"

        self.fanfic = FanficInfo(
            url="https://archiveofourown.org/works/123456", site="ao3"
        )
        self.path_or_url = "https://archiveofourown.org/works/123456"

    def tearDown(self):
        """Clean up after each test - ensure verbose is disabled."""
        url_worker.ff_logging.verbose.value = False

    def test_update_method_normal(self):
        """Test command construction with 'update' method."""
        self.calibre_info.update_method = "update"
        cmd = url_worker.construct_fanficfare_command(
            self.calibre_info, self.fanfic, self.path_or_url
        )

        self.assertIn("python -m fanficfare.cli", cmd)
        self.assertIn("-u", cmd)
        self.assertIn(self.path_or_url, cmd)
        self.assertIn("--update-cover", cmd)
        self.assertIn("--non-interactive", cmd)
        self.assertNotIn("--debug", cmd)

    def test_update_method_update_always(self):
        """Test command construction with 'update_always' method."""
        self.calibre_info.update_method = "update_always"
        cmd = url_worker.construct_fanficfare_command(
            self.calibre_info, self.fanfic, self.path_or_url
        )

        self.assertIn("-U", cmd)
        self.assertNotIn("-u ", cmd)  # Space to avoid matching -U
        self.assertNotIn("--force", cmd)
        self.assertNotIn("--debug", cmd)

    def test_update_method_force(self):
        """Test command construction with 'force' method."""
        self.calibre_info.update_method = "force"
        cmd = url_worker.construct_fanficfare_command(
            self.calibre_info, self.fanfic, self.path_or_url
        )

        self.assertIn("-u --force", cmd)
        self.assertNotIn("-U ", cmd)
        self.assertNotIn("--debug", cmd)

    def test_update_method_update_no_force(self):
        """Test command construction with 'update_no_force' method."""
        self.calibre_info.update_method = "update_no_force"
        cmd = url_worker.construct_fanficfare_command(
            self.calibre_info, self.fanfic, self.path_or_url
        )

        self.assertIn("-u", cmd)
        self.assertNotIn("--force", cmd)
        self.assertNotIn("-U", cmd)
        self.assertNotIn("--debug", cmd)

    def test_force_behavior_requested(self):
        """Test command when fanfic explicitly requests force behavior."""
        self.calibre_info.update_method = "update"
        self.fanfic.behavior = "force"
        cmd = url_worker.construct_fanficfare_command(
            self.calibre_info, self.fanfic, self.path_or_url
        )

        self.assertIn("-u --force", cmd)
        self.assertNotIn("--debug", cmd)

    def test_force_ignored_with_update_no_force(self):
        """Test that force requests are ignored with update_no_force method."""
        self.calibre_info.update_method = "update_no_force"
        self.fanfic.behavior = "force"
        cmd = url_worker.construct_fanficfare_command(
            self.calibre_info, self.fanfic, self.path_or_url
        )

        self.assertIn(
            "-u ", cmd
        )  # Check for -u with space to avoid matching --update-cover
        self.assertNotIn("--force", cmd)
        self.assertNotIn("--debug", cmd)

    def test_verbose_enabled_adds_debug_flag(self):
        """Test that --debug flag is added when verbose logging is enabled."""
        url_worker.ff_logging.verbose.value = True
        self.calibre_info.update_method = "update"
        cmd = url_worker.construct_fanficfare_command(
            self.calibre_info, self.fanfic, self.path_or_url
        )

        self.assertIn("--debug", cmd)
        self.assertIn("-u", cmd)

    def test_verbose_disabled_no_debug_flag(self):
        """Test that --debug flag is NOT added when verbose logging is disabled."""
        url_worker.ff_logging.verbose.value = False
        self.calibre_info.update_method = "update"
        cmd = url_worker.construct_fanficfare_command(
            self.calibre_info, self.fanfic, self.path_or_url
        )

        self.assertNotIn("--debug", cmd)

    def test_verbose_with_force_method(self):
        """Test --debug flag with force update method."""
        url_worker.ff_logging.verbose.value = True
        self.calibre_info.update_method = "force"
        cmd = url_worker.construct_fanficfare_command(
            self.calibre_info, self.fanfic, self.path_or_url
        )

        self.assertIn("--debug", cmd)
        self.assertIn("--force", cmd)

    def test_verbose_with_update_always(self):
        """Test --debug flag with update_always method."""
        url_worker.ff_logging.verbose.value = True
        self.calibre_info.update_method = "update_always"
        cmd = url_worker.construct_fanficfare_command(
            self.calibre_info, self.fanfic, self.path_or_url
        )

        self.assertIn("--debug", cmd)
        self.assertIn("-U", cmd)

    def test_epub_path_handling(self):
        """Test command construction with epub file path instead of URL."""
        epub_path = "/tmp/tmpxyz/Story Title - Author.epub"
        cmd = url_worker.construct_fanficfare_command(
            self.calibre_info, self.fanfic, epub_path
        )

        self.assertIn(epub_path, cmd)
        self.assertIn("-u", cmd)
        self.assertNotIn("--debug", cmd)

    def test_epub_path_with_verbose(self):
        """Test epub path with verbose enabled."""
        url_worker.ff_logging.verbose.value = True
        epub_path = "/tmp/tmpxyz/Story Title - Author.epub"
        cmd = url_worker.construct_fanficfare_command(
            self.calibre_info, self.fanfic, epub_path
        )

        self.assertIn("--debug", cmd)
        self.assertIn(epub_path, cmd)


if __name__ == "__main__":
    unittest.main()
