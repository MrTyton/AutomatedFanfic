from subprocess import STDOUT, PIPE
import unittest
from unittest.mock import MagicMock, patch
from parameterized import parameterized
import multiprocessing as mp

import url_worker
from fanfic_info import FanficInfo
from calibre_info import CalibreInfo
from notification_base import NotificationBase
from typing import NamedTuple, Optional


class TestUrlWorker(unittest.TestCase):
    class HandleFailureTestCase(NamedTuple):
        reached_maximum_repeats: bool
        expected_log_failure_call: bool
        expected_notification_call: bool
        expected_queue_put_call: bool

    @parameterized.expand(
        [
            HandleFailureTestCase(
                reached_maximum_repeats=True,
                expected_log_failure_call=True,
                expected_notification_call=True,
                expected_queue_put_call=False,
            ),
            HandleFailureTestCase(
                reached_maximum_repeats=False,
                expected_log_failure_call=False,
                expected_notification_call=False,
                expected_queue_put_call=True,
            ),
        ]
    )
    @patch("ff_logging.log_failure")
    def test_handle_failure(
        self,
        reached_maximum_repeats,
        expected_log_failure_call,
        expected_notification_call,
        expected_queue_put_call,
        mock_log_failure,
    ):
        # Setup
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "site"
        mock_fanfic.reached_maximum_repeats.return_value = (
            reached_maximum_repeats
        )
        mock_notification_info = MagicMock(spec=NotificationBase)
        mock_queue = MagicMock(spec=mp.Queue)
        mock_queue.put = MagicMock()

        # Execution
        url_worker.handle_failure(
            mock_fanfic, mock_notification_info, mock_queue
        )

        # Assertions
        if expected_log_failure_call:
            mock_log_failure.assert_called_once_with(
                f"Maximum attempts reached for {mock_fanfic.url}. Skipping."
            )
        else:
            mock_log_failure.assert_not_called()

        if expected_notification_call:
            mock_notification_info.send_notification.assert_called_once_with(
                "Fanfiction Download Failed", mock_fanfic.url, mock_fanfic.site
            )
        else:
            mock_notification_info.send_notification.assert_not_called()

        if expected_queue_put_call:
            mock_queue.put.assert_called_once_with(mock_fanfic)
        else:
            mock_queue.put.assert_not_called()

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
        result = url_worker.get_path_or_url(
            mock_fanfic, mock_cdb_info, "/fake/path"
        )

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

    class ProcessFanficAdditionTestCase(NamedTuple):
        calibre_id: Optional[int]
        get_id_from_calibredb: bool
        expected_log_failure_call: bool
        success_notification_call: bool

    @parameterized.expand(
        [
            ProcessFanficAdditionTestCase(
                calibre_id=123,
                get_id_from_calibredb=False,
                expected_log_failure_call=True,
                success_notification_call=False,
            ),
            ProcessFanficAdditionTestCase(
                calibre_id=None,
                get_id_from_calibredb=True,
                expected_log_failure_call=False,
                success_notification_call=True,
            ),
        ]
    )
    @patch("calibredb_utils.add_story")
    @patch("calibredb_utils.remove_story")
    @patch("ff_logging.log_failure")
    def test_process_fanfic_addition(
        self,
        calibre_id,
        get_id_from_calibredb,
        expected_log_failure_call,
        success_notification_call,
        mock_log_failure,
        mock_remove_story,
        mock_add_story,
    ):
        # Setup
        mock_fanfic = MagicMock(spec=FanficInfo)
        mock_fanfic.calibre_id = calibre_id
        mock_fanfic.get_id_from_calibredb.return_value = get_id_from_calibredb
        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "site"
        mock_fanfic.title = "title"
        mock_cdb = MagicMock(spec=CalibreInfo)
        mock_notification_info = MagicMock(spec=NotificationBase)
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
        if calibre_id:
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

        if expected_log_failure_call:
            self.assertEqual(mock_log_failure.call_count, 2)
            mock_log_failure.assert_any_call(
                "\t(site) Failed to add path_or_url to Calibre"
            )
            mock_log_failure.assert_any_call(
                "Maximum attempts reached for http://example.com/story. Skipping."
            )
        else:
            mock_log_failure.assert_not_called()

        if success_notification_call:
            mock_notification_info.send_notification.assert_called_once_with(
                "New Fanfiction Download", mock_fanfic.title, "site"
            )
        else:
            mock_notification_info.send_notification.assert_called_once_with(
                "Fanfiction Download Failed", "http://example.com/story", "site"
            )


if __name__ == "__main__":
    unittest.main()
