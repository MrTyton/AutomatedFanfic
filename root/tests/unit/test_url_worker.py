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

    @patch("ff_logging.log_failure")
    def test_handle_failure_update_no_force(self, mock_log_failure):
        """Test handle_failure with update_no_force scenarios."""
        # Setup common mocks
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "test_site"
        mock_fanfic.behavior = "force"
        mock_notification_info = MagicMock(spec=NotificationWrapper)
        mock_queue = MagicMock(spec=mp.Queue)
        mock_queue.put = MagicMock()  # Explicitly add the put method

        # Test Case 1: Hail Mary with force + update_no_force -> should send notification
        mock_fanfic.reached_maximum_repeats.return_value = (True, True)
        mock_cdb = MagicMock(spec=CalibreInfo)
        mock_cdb.update_method = "update_no_force"

        url_worker.handle_failure(
            mock_fanfic, mock_notification_info, mock_queue, mock_cdb
        )

        # Assertions for Case 1
        mock_log_failure.assert_called_once_with(
            "Hail Mary attempted for http://example.com/story and failed."
        )
        mock_notification_info.send_notification.assert_called_once_with(
            "Fanfiction Update Permanently Skipped",
            "Update for http://example.com/story was permanently skipped because a force was requested but the update method is set to 'update_no_force'. The force request was ignored and a normal update was attempted instead.",
            "test_site",
        )
        mock_queue.put.assert_not_called()

        # Reset mocks for next test
        mock_log_failure.reset_mock()
        mock_notification_info.reset_mock()
        mock_queue.reset_mock()

        # Test Case 2: Hail Mary with non-force behavior + update_no_force -> should not send notification
        mock_fanfic.behavior = "update"  # Not force

        url_worker.handle_failure(
            mock_fanfic, mock_notification_info, mock_queue, mock_cdb
        )

        # Assertions for Case 2
        mock_log_failure.assert_called_once_with(
            "Hail Mary attempted for http://example.com/story and failed."
        )
        mock_notification_info.send_notification.assert_not_called()  # Should not send notification
        mock_queue.put.assert_not_called()

        # Reset mocks for next test
        mock_log_failure.reset_mock()
        mock_notification_info.reset_mock()
        mock_queue.reset_mock()

        # Test Case 3: Hail Mary with force + different update_method -> should not send notification
        mock_fanfic.behavior = "force"
        mock_cdb.update_method = "update_always"  # Not update_no_force

        url_worker.handle_failure(
            mock_fanfic, mock_notification_info, mock_queue, mock_cdb
        )

        # Assertions for Case 3
        mock_log_failure.assert_called_once_with(
            "Hail Mary attempted for http://example.com/story and failed."
        )
        mock_notification_info.send_notification.assert_not_called()  # Should not send notification
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

    @patch("ff_logging.log_failure")
    def test_handle_failure_edge_cases(self, mock_log_failure):
        """Test handle_failure edge cases with different behavior values."""
        # Setup common mocks
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "test_site"
        mock_notification_info = MagicMock(spec=NotificationWrapper)
        mock_queue = MagicMock(spec=mp.Queue)
        mock_queue.put = MagicMock()
        mock_cdb = MagicMock(spec=CalibreInfo)
        mock_cdb.update_method = "update_no_force"

        # Test Case 1: None behavior (should not trigger special notification)
        mock_fanfic.behavior = None
        mock_fanfic.reached_maximum_repeats.return_value = (True, True)

        url_worker.handle_failure(
            mock_fanfic, mock_notification_info, mock_queue, mock_cdb
        )

        mock_log_failure.assert_called_once_with(
            "Hail Mary attempted for http://example.com/story and failed."
        )
        mock_notification_info.send_notification.assert_not_called()

        # Reset mocks for next test
        mock_log_failure.reset_mock()
        mock_notification_info.reset_mock()

        # Test Case 2: Empty string behavior (should not trigger special notification)
        mock_fanfic.behavior = ""

        url_worker.handle_failure(
            mock_fanfic, mock_notification_info, mock_queue, mock_cdb
        )

        mock_log_failure.assert_called_once_with(
            "Hail Mary attempted for http://example.com/story and failed."
        )
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


if __name__ == "__main__":
    unittest.main()
