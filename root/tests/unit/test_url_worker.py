import unittest
from unittest.mock import MagicMock, patch, call
from parameterized import parameterized
import multiprocessing as mp
from subprocess import STDOUT, PIPE

import url_worker
from fanfic_info import FanficInfo
from calibre_info import CalibreInfo
from notification_wrapper import NotificationWrapper
import ff_logging
import regex_parsing
import system_utils
from typing import NamedTuple, Optional


class TestUrlWorker(unittest.TestCase):
    class HandleFailureTestCase(NamedTuple):
        reached_maximum_repeats: bool
        hail_mary: bool  # Added hail_mary flag
        expected_log_failure_call: bool
        expected_log_message: Optional[str]  # Specific message expected
        expected_notification_call: bool
        expected_notification_title: Optional[str]  # Specific notification title
        expected_queue_put_call: bool

    @parameterized.expand(
        [
            # Case 1: Not reached maximum repeats
            HandleFailureTestCase(
                reached_maximum_repeats=False,
                hail_mary=False,
                expected_log_failure_call=False,
                expected_log_message=None,
                expected_notification_call=False,
                expected_notification_title=None,
                expected_queue_put_call=True,
            ),
            # Case 2: Reached maximum repeats, hail_mary not yet attempted
            HandleFailureTestCase(
                reached_maximum_repeats=True,
                hail_mary=False,
                expected_log_failure_call=True,
                expected_log_message="Maximum attempts reached for http://example.com/story. Activating Hail-Mary Protocol.",
                expected_notification_call=True,
                expected_notification_title="Fanfiction Download Failed, trying Hail-Mary in 12 hours.",
                expected_queue_put_call=False,
            ),
            # Case 3: Reached maximum repeats, hail_mary already attempted
            HandleFailureTestCase(
                reached_maximum_repeats=True,
                hail_mary=True,
                expected_log_failure_call=True,
                expected_log_message="Hail Mary attempted for http://example.com/story and failed.",
                expected_notification_call=False,
                expected_notification_title=None,
                expected_queue_put_call=False,
            ),
        ]
    )
    @patch("ff_logging.log_failure")
    def test_handle_failure(
        self,
        reached_maximum_repeats,
        hail_mary,
        expected_log_failure_call,
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
        # Mock reached_maximum_repeats to return a tuple
        mock_fanfic.reached_maximum_repeats.return_value = (
            reached_maximum_repeats,
            hail_mary,
        )
        mock_notification_info = MagicMock(spec=NotificationWrapper)
        mock_queue = MagicMock(spec=mp.Queue)
        mock_queue.put = MagicMock()
        mock_fanfic.increment_repeat = MagicMock()  # Ensure increment_repeat is mocked

        # Execution
        url_worker.handle_failure(mock_fanfic, mock_notification_info, mock_queue, None)

        # Assertions
        if expected_log_failure_call:
            mock_log_failure.assert_called_once_with(expected_log_message)
        else:
            mock_log_failure.assert_not_called()

        if expected_notification_call:
            mock_notification_info.send_notification.assert_called_once_with(
                expected_notification_title, mock_fanfic.url, mock_fanfic.site
            )
        else:
            mock_notification_info.send_notification.assert_not_called()

        if expected_queue_put_call:
            mock_fanfic.increment_repeat.assert_called_once()  # Check increment call
            mock_queue.put.assert_called_once_with(mock_fanfic)
        else:
            mock_fanfic.increment_repeat.assert_not_called()  # Check increment not called
            mock_queue.put.assert_not_called()

    class HandleFailureUpdateNoForceTestCase(NamedTuple):
        name: str
        behavior: str
        update_method: str
        reached_maximum_repeats: tuple[bool, bool]
        should_send_notification: bool
        expected_notification_title: str
        expected_notification_body: str
        expected_log_message: str

    @parameterized.expand([
        HandleFailureUpdateNoForceTestCase(
            name="hail_mary_force_update_no_force",
            behavior="force",
            update_method="update_no_force",
            reached_maximum_repeats=(True, True),
            should_send_notification=True,
            expected_notification_title="Fanfiction Update Permanently Skipped",
            expected_notification_body="Update for http://example.com/story was permanently skipped because a force was requested but the update method is set to 'update_no_force'. The force request was ignored and a normal update was attempted instead.",
            expected_log_message="Hail Mary attempted for http://example.com/story and failed."
        ),
        HandleFailureUpdateNoForceTestCase(
            name="hail_mary_non_force_update_no_force",
            behavior="update",
            update_method="update_no_force",
            reached_maximum_repeats=(True, True),
            should_send_notification=False,
            expected_notification_title="",
            expected_notification_body="",
            expected_log_message="Hail Mary attempted for http://example.com/story and failed."
        ),
        HandleFailureUpdateNoForceTestCase(
            name="hail_mary_force_different_update_method",
            behavior="force",
            update_method="update_always",
            reached_maximum_repeats=(True, True),
            should_send_notification=False,
            expected_notification_title="",
            expected_notification_body="",
            expected_log_message="Hail Mary attempted for http://example.com/story and failed."
        ),
    ])
    @patch("ff_logging.log_failure")
    def test_handle_failure_update_no_force(self, name, behavior, update_method, 
                                          reached_maximum_repeats, should_send_notification, 
                                          expected_notification_title, expected_notification_body, 
                                          expected_log_message, mock_log_failure):
        """Test handle_failure with update_no_force scenarios."""
        # Setup common mocks
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "test_site"
        mock_fanfic.behavior = behavior
        mock_fanfic.reached_maximum_repeats.return_value = reached_maximum_repeats
        mock_notification_info = MagicMock(spec=NotificationWrapper)
        mock_queue = MagicMock(spec=mp.Queue)
        mock_queue.put = MagicMock()
        mock_cdb = MagicMock(spec=CalibreInfo)
        mock_cdb.update_method = update_method

        url_worker.handle_failure(
            mock_fanfic, mock_notification_info, mock_queue, mock_cdb
        )

        # Assertions
        mock_log_failure.assert_called_once_with(expected_log_message)
        
        if should_send_notification:
            mock_notification_info.send_notification.assert_called_once_with(
                expected_notification_title,
                expected_notification_body,
                "test_site",
            )
        else:
            mock_notification_info.send_notification.assert_not_called()
        
        mock_queue.put.assert_not_called()

    @patch("ff_logging.log_failure")
    def test_handle_failure_with_none_cdb(self, mock_log_failure):
        """Test handle_failure with cdb=None (should never send special notification)."""
        # Setup common mocks
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "test_site"
        mock_fanfic.behavior = "force"
        mock_notification_info = MagicMock(spec=NotificationWrapper)
        mock_queue = MagicMock(spec=mp.Queue)
        mock_queue.put = MagicMock()

        # Test Case: Hail Mary with force behavior but cdb=None -> should not send special notification
        mock_fanfic.reached_maximum_repeats.return_value = (True, True)

        url_worker.handle_failure(mock_fanfic, mock_notification_info, mock_queue, None)

        # Assertions - should log but not send special notification
        mock_log_failure.assert_called_once_with(
            "Hail Mary attempted for http://example.com/story and failed."
        )
        mock_notification_info.send_notification.assert_not_called()
        mock_queue.put.assert_not_called()

    class HandleFailureEdgeCaseTestCase(NamedTuple):
        name: str
        behavior: str | None
        reached_maximum_repeats: tuple[bool, bool]
        expected_log_message: str

    @parameterized.expand([
        HandleFailureEdgeCaseTestCase(
            name="none_behavior",
            behavior=None,
            reached_maximum_repeats=(True, True),
            expected_log_message="Hail Mary attempted for http://example.com/story and failed."
        ),
        HandleFailureEdgeCaseTestCase(
            name="empty_behavior",
            behavior="",
            reached_maximum_repeats=(True, True),
            expected_log_message="Hail Mary attempted for http://example.com/story and failed."
        ),
    ])
    @patch("ff_logging.log_failure")
    def test_handle_failure_edge_cases(self, name, behavior, reached_maximum_repeats, expected_log_message, mock_log_failure):
        """Test handle_failure edge cases with different behavior values."""
        # Setup common mocks
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "test_site"
        mock_fanfic.behavior = behavior
        mock_fanfic.reached_maximum_repeats.return_value = reached_maximum_repeats
        mock_notification_info = MagicMock(spec=NotificationWrapper)
        mock_queue = MagicMock(spec=mp.Queue)
        mock_queue.put = MagicMock()
        mock_cdb = MagicMock(spec=CalibreInfo)
        mock_cdb.update_method = "update_no_force"

        url_worker.handle_failure(
            mock_fanfic, mock_notification_info, mock_queue, mock_cdb
        )

        mock_log_failure.assert_called_once_with(expected_log_message)
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
    @patch("calibredb_utils.export_story")
    def test_get_path_or_url(
        self,
        fanfic_in_calibre,
        exported_files,
        expected_result,
        mock_export_story,
        mock_get_files,
    ):
        # Setup
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.get_id_from_calibredb.return_value = fanfic_in_calibre
        mock_fanfic.url = "http://example.com/story"
        mock_cdb_info = MagicMock(spec=CalibreInfo)
        mock_get_files.return_value = exported_files

        # Execution
        result = url_worker.get_path_or_url(mock_fanfic, mock_cdb_info, "/fake/path")

        # Assertions
        self.assertEqual(result, expected_result)
        if fanfic_in_calibre:
            mock_export_story.assert_called_once_with(
                fanfic_info=mock_fanfic,
                location="/fake/path",
                calibre_info=mock_cdb_info,
            )
        else:
            mock_export_story.assert_not_called()

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
            command, shell=True, stderr=STDOUT, stdin=PIPE
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
            "failed_command", shell=True, stderr=STDOUT, stdin=PIPE
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
            "test command", shell=True, stderr=STDOUT, stdin=PIPE
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
    @patch("calibredb_utils.add_story")
    @patch("calibredb_utils.remove_story")
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
        mock_remove_story,
        mock_add_story,
        mock_handle_failure,  # Add mock for handle_failure
    ):
        # Setup
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.calibre_id = calibre_id
        # Configure the return value of get_id_from_calibredb
        mock_fanfic.get_id_from_calibredb.return_value = get_id_from_calibredb_returns
        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "site"
        mock_fanfic.title = "title"
        mock_cdb = MagicMock(spec=CalibreInfo)
        mock_notification_info = MagicMock(spec=NotificationWrapper)
        mock_queue = MagicMock(spec=mp.Queue)

        # Execution
        url_worker.process_fanfic_addition(
            mock_fanfic,
            mock_cdb,
            "/fake/temp/dir",
            "site",
            "path_or_url",
            mock_queue,
            mock_notification_info,
        )

        # Assertions
        if expected_remove_story_call:
            mock_remove_story.assert_called_once_with(
                fanfic_info=mock_fanfic, calibre_info=mock_cdb
            )
        else:
            mock_remove_story.assert_not_called()

        mock_add_story.assert_called_once_with(
            location="/fake/temp/dir",
            fanfic_info=mock_fanfic,
            calibre_info=mock_cdb,
        )

        # Check if get_id_from_calibredb was called after add_story
        mock_fanfic.get_id_from_calibredb.assert_called_once_with(mock_cdb)

        if expected_handle_failure_call:
            # Check if the specific log message before handle_failure was called
            mock_log_failure.assert_called_once_with(
                "\t(site) Failed to add path_or_url to Calibre"
            )
            # Check if handle_failure was called
            mock_handle_failure.assert_called_once_with(
                mock_fanfic, mock_notification_info, mock_queue, mock_cdb
            )
            # Ensure success notification was NOT called if handle_failure was called
            mock_notification_info.send_notification.assert_not_called()
        else:
            # Ensure log_failure was NOT called if addition succeeded
            mock_log_failure.assert_not_called()
            # Ensure handle_failure was NOT called
            mock_handle_failure.assert_not_called()
            # Check if the success notification was called
            if expected_success_notification_call:
                mock_notification_info.send_notification.assert_called_once_with(
                    "New Fanfiction Download", mock_fanfic.title, "site"
                )
            else:
                # This case shouldn't happen with the current logic (success add but no success notification expected)
                # but included for completeness.
                mock_notification_info.send_notification.assert_not_called()


class TestUrlWorkerMainLoop(unittest.TestCase):
    """Test the main url_worker() function loop that processes fanfics from queue."""

    def setUp(self):
        """Set up common mocks for url_worker main loop tests."""
        self.mock_queue = MagicMock()
        self.mock_cdb = MagicMock(spec=CalibreInfo)
        self.mock_notification_info = MagicMock(spec=NotificationWrapper)
        self.mock_waiting_queue = MagicMock()
        
        # Create test fanfic object
        self.test_fanfic = MagicMock(spec=FanficInfo)
        self.test_fanfic.site = "test_site"
        self.test_fanfic.url = "http://example.com/story"
        self.test_fanfic.behavior = "update"
        
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

    @patch('url_worker.system_utils.temporary_directory')
    @patch('url_worker.get_path_or_url')
    @patch('url_worker.construct_fanficfare_command')
    @patch('url_worker.ff_logging.log')
    @patch('url_worker.handle_failure')
    def test_url_worker_force_update_no_force_exception(
        self,
        mock_handle_failure,
        mock_log,
        mock_construct_cmd,
        mock_get_path,
        mock_temp_dir,
    ):
        """Test exception handling for force request with update_no_force configuration."""
        # Set up fanfic that requests force with update_no_force config
        self.test_fanfic.behavior = "force"
        self.mock_cdb.update_method = "update_no_force"
        
        # Set up queue behavior
        self.mock_queue.empty.return_value = False
        self.mock_queue.get.side_effect = self.create_queue_get_side_effect(self.test_fanfic)
        
        # Set up temp directory and basic processing
        mock_temp_dir.return_value.__enter__.return_value = "/tmp/test"
        mock_get_path.return_value = "test_file.epub"
        mock_construct_cmd.return_value = "fanficfare command"
        
        # Mock logging failure to capture the specific error message
        with patch('url_worker.ff_logging.log_failure') as mock_log_failure:
            # Run worker - will exit with KeyboardInterrupt after processing
            with self.assertRaises(KeyboardInterrupt):
                url_worker.url_worker(
                    self.mock_queue, self.mock_cdb, self.mock_notification_info, self.mock_waiting_queue
                )
            
            # Verify that exception was triggered and failure handler called
            mock_log_failure.assert_called_once_with(
                "\t(test_site) Failed to update test_file.epub: Force update requested but update method is 'update_no_force'"
            )
            mock_handle_failure.assert_called_once_with(
                self.test_fanfic, self.mock_notification_info, self.mock_waiting_queue, self.mock_cdb
            )

    @patch('url_worker.execute_command')
    @patch('url_worker.system_utils.copy_configs_to_temp_dir')
    @patch('url_worker.system_utils.temporary_directory')
    @patch('url_worker.get_path_or_url')
    @patch('url_worker.construct_fanficfare_command')
    @patch('url_worker.ff_logging.log')
    @patch('url_worker.handle_failure')
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
        self.mock_queue.get.side_effect = self.create_queue_get_side_effect(self.test_fanfic)
        
        # Set up temp directory and processing until execute_command
        mock_temp_dir.return_value.__enter__.return_value = "/tmp/test"
        mock_get_path.return_value = "test_file.epub"
        mock_construct_cmd.return_value = "fanficfare command"
        mock_execute.side_effect = Exception("Command execution failed")
        
        # Mock logging failure to capture the specific error message
        with patch('url_worker.ff_logging.log_failure') as mock_log_failure:
            # Run worker - will exit with KeyboardInterrupt after processing
            with self.assertRaises(KeyboardInterrupt):
                url_worker.url_worker(
                    self.mock_queue, self.mock_cdb, self.mock_notification_info, self.mock_waiting_queue
                )
            
            # Verify that exception was caught and failure handler called
            mock_log_failure.assert_called_once_with(
                "\t(test_site) Failed to update test_file.epub: Command execution failed"
            )
            mock_handle_failure.assert_called_once_with(
                self.test_fanfic, self.mock_notification_info, self.mock_waiting_queue, self.mock_cdb
            )

    @patch('url_worker.execute_command')
    @patch('url_worker.system_utils.copy_configs_to_temp_dir')
    @patch('url_worker.system_utils.temporary_directory')
    @patch('url_worker.get_path_or_url')
    @patch('url_worker.construct_fanficfare_command')
    @patch('url_worker.regex_parsing.check_failure_regexes')
    @patch('url_worker.ff_logging.log')
    @patch('url_worker.handle_failure')
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
        self.mock_queue.get.side_effect = self.create_queue_get_side_effect(self.test_fanfic)
        
        # Set up successful execution but failure regex detection
        mock_temp_dir.return_value.__enter__.return_value = "/tmp/test"
        mock_get_path.return_value = "test_file.epub"
        mock_construct_cmd.return_value = "fanficfare command"
        mock_execute.return_value = "output with failure indicators"
        mock_check_failure.return_value = False  # Failure detected
        
        # Run worker - will exit with KeyboardInterrupt after processing
        with self.assertRaises(KeyboardInterrupt):
            url_worker.url_worker(
                self.mock_queue, self.mock_cdb, self.mock_notification_info, self.mock_waiting_queue
            )
        
        # Verify failure handler was called due to regex detection
        mock_handle_failure.assert_called_once_with(
            self.test_fanfic, self.mock_notification_info, self.mock_waiting_queue, self.mock_cdb
        )

    @patch('url_worker.execute_command')
    @patch('url_worker.system_utils.copy_configs_to_temp_dir')
    @patch('url_worker.system_utils.temporary_directory')
    @patch('url_worker.get_path_or_url')
    @patch('url_worker.construct_fanficfare_command')
    @patch('url_worker.regex_parsing.check_failure_regexes')
    @patch('url_worker.regex_parsing.check_forceable_regexes')
    @patch('url_worker.ff_logging.log')
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
        self.mock_queue.get.side_effect = self.create_queue_get_side_effect(self.test_fanfic)
        
        # Set up successful execution with forceable condition
        mock_temp_dir.return_value.__enter__.return_value = "/tmp/test"
        mock_get_path.return_value = "test_file.epub"
        mock_construct_cmd.return_value = "fanficfare command"
        mock_execute.return_value = "output with forceable condition"
        mock_check_failure.return_value = True  # No permanent failure
        mock_check_forceable.return_value = True  # Force retry needed
        
        # Run worker - will exit with KeyboardInterrupt after processing
        with self.assertRaises(KeyboardInterrupt):
            url_worker.url_worker(
                self.mock_queue, self.mock_cdb, self.mock_notification_info, self.mock_waiting_queue
            )
        
        # Verify fanfic was re-queued with force behavior
        self.assertEqual(self.test_fanfic.behavior, "force")
        self.mock_queue.put.assert_called_once_with(self.test_fanfic)

    @patch('url_worker.process_fanfic_addition')
    @patch('url_worker.execute_command')
    @patch('url_worker.system_utils.copy_configs_to_temp_dir')
    @patch('url_worker.system_utils.temporary_directory')
    @patch('url_worker.get_path_or_url')
    @patch('url_worker.construct_fanficfare_command')
    @patch('url_worker.regex_parsing.check_failure_regexes')
    @patch('url_worker.regex_parsing.check_forceable_regexes')
    @patch('url_worker.ff_logging.log')
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
        self.mock_queue.get.side_effect = self.create_queue_get_side_effect(self.test_fanfic)
        
        # Set up successful processing path
        mock_temp_dir.return_value.__enter__.return_value = "/tmp/test"
        mock_get_path.return_value = "test_file.epub"
        mock_construct_cmd.return_value = "fanficfare command"
        mock_execute.return_value = "successful output"
        mock_check_failure.return_value = True  # No failure
        mock_check_forceable.return_value = False  # No force needed
        
        # Run worker - will exit with KeyboardInterrupt after processing
        with self.assertRaises(KeyboardInterrupt):
            url_worker.url_worker(
                self.mock_queue, self.mock_cdb, self.mock_notification_info, self.mock_waiting_queue
            )
        
        # Verify successful processing
        mock_process_addition.assert_called_once_with(
            self.test_fanfic,
            self.mock_cdb,
            "/tmp/test",
            "test_site",
            "test_file.epub",
            self.mock_waiting_queue,
            self.mock_notification_info,
        )

if __name__ == "__main__":
    unittest.main()
