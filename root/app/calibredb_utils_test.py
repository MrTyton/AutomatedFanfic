import unittest
from unittest.mock import MagicMock, patch
from parameterized import parameterized
from typing import NamedTuple, Optional

import fanfic_info
import calibre_info
from calibredb_utils import (
    call_calibre_db,
    export_story,
    remove_story,
    add_story,
)


class CallCalibreDbTestCase(unittest.TestCase):
    class CallCalibreDbParams(NamedTuple):
        command: str
        calibre_info: calibre_info.CalibreInfo
        fanfic_info: Optional[fanfic_info.FanficInfo]
        expected_command: str
        should_raise_exception: bool

    @parameterized.expand(
        [
            CallCalibreDbParams(
                command="list",
                calibre_info=MagicMock(),
                fanfic_info=None,
                expected_command="list ",
                should_raise_exception=False,
            ),
            CallCalibreDbParams(
                command="add",
                calibre_info=MagicMock(),
                fanfic_info=MagicMock(calibre_id="123"),
                expected_command="add 123",
                should_raise_exception=False,
            ),
            CallCalibreDbParams(
                command="remove",
                calibre_info=MagicMock(),
                fanfic_info=MagicMock(calibre_id="123"),
                expected_command="remove 123",
                should_raise_exception=True,
            ),
        ]
    )
    @patch("calibredb_utils.call", return_value=None)
    @patch("calibredb_utils.ff_logging.log_failure")
    @patch("calibredb_utils.ff_logging.log_debug")
    def test_call_calibre_db(
        self,
        command,
        calibre_info,
        fanfic_info,
        expected_command,
        should_raise_exception,
        mock_log_debug,
        mock_log_failure,
        mock_call,
    ):
        calibre_info.lock = MagicMock()

        if should_raise_exception:
            mock_call.side_effect = Exception("Test exception")

        call_calibre_db(command, calibre_info, fanfic_info)

        mock_log_debug.assert_called_once_with(
            f'\tCalling calibredb with command: \t"{expected_command} {calibre_info}"'
        )

        if should_raise_exception:
            mock_log_failure.assert_called_once()
        else:
            mock_log_failure.assert_not_called()


class ExportStoryTestCase(unittest.TestCase):
    class ExportStoryParams(NamedTuple):
        fanfic_info: fanfic_info.FanficInfo
        location: str
        calibre_info: calibre_info.CalibreInfo
        expected_command: str

    @parameterized.expand(
        [
            ExportStoryParams(
                fanfic_info=MagicMock(),
                location="/fake/location",
                calibre_info=MagicMock(),
                expected_command='export --dont-save-cover --dont-write-opf --single-dir --to-dir "/fake/location"',
            ),
        ]
    )
    @patch("calibredb_utils.call_calibre_db")
    def test_export_story(
        self,
        fanfic_info,
        location,
        calibre_info,
        expected_command,
        mock_call_calibre_db,
    ):
        export_story(
            fanfic_info=fanfic_info,
            location=location,
            calibre_info=calibre_info,
        )
        mock_call_calibre_db.assert_called_once_with(
            expected_command, calibre_info, fanfic_info
        )


class RemoveStoryTestCase(unittest.TestCase):
    class RemoveStoryParams(NamedTuple):
        fanfic_info: fanfic_info.FanficInfo
        calibre_info: calibre_info.CalibreInfo
        expected_command: str

    @parameterized.expand(
        [
            RemoveStoryParams(
                fanfic_info=MagicMock(calibre_id="123"),
                calibre_info=MagicMock(),
                expected_command="remove",
            ),
        ]
    )
    @patch("calibredb_utils.call_calibre_db")
    def test_remove_story(
        self,
        fanfic_info,
        calibre_info,
        expected_command,
        mock_call_calibre_db,
    ):
        remove_story(fanfic_info, calibre_info)
        mock_call_calibre_db.assert_called_once_with(
            expected_command, calibre_info, fanfic_info
        )


class AddStoryTestCase(unittest.TestCase):
    class AddStoryParams(NamedTuple):
        location: str
        fanfic_info: fanfic_info.FanficInfo
        calibre_info: calibre_info.CalibreInfo
        epub_files: list
        expected_command: str
        should_fail: bool

    @parameterized.expand(
        [
            AddStoryParams(
                location="/fake/location",
                fanfic_info=MagicMock(),
                calibre_info=MagicMock(return_value="mock_calibre_info"),
                epub_files=["/fake/location/story.epub"],
                expected_command='add -d {mock} "/fake/location/story.epub"',
                should_fail=False,
            ),
            AddStoryParams(
                location="/fake/location",
                fanfic_info=MagicMock(),
                calibre_info=MagicMock(return_value="mock_calibre_info"),
                epub_files=[],
                expected_command="",
                should_fail=True,
            ),
        ]
    )
    @patch("calibredb_utils.system_utils.get_files")
    @patch(
        "calibredb_utils.regex_parsing.extract_filename",
        return_value="Story Title",
    )
    @patch("calibredb_utils.call_calibre_db")
    @patch("calibredb_utils.ff_logging.log_failure")
    @patch("calibredb_utils.ff_logging.log")
    def test_add_story(
        self,
        location,
        fanfic_info,
        calibre_info,
        epub_files,
        expected_command,
        should_fail,
        mock_log,
        mock_log_failure,
        mock_call_calibre_db,
        mock_extract_filename,
        mock_get_files,
    ):
        mock_get_files.return_value = epub_files
        calibre_info.return_value = "mock_calibre_info"

        add_story(
            location=location,
            fanfic_info=fanfic_info,
            calibre_info=calibre_info,
        )

        if should_fail:
            mock_log_failure.assert_called_once_with(
                "No EPUB files found in the specified location."
            )
            mock_call_calibre_db.assert_not_called()
        else:
            mock_log.assert_called_once_with(
                f"\t({fanfic_info.site}) Adding {epub_files[0]} to Calibre",
                "OKGREEN",
            )
            mock_call_calibre_db.assert_called_once_with(
                expected_command.format(mock=calibre_info),
                calibre_info,
                fanfic_info=None,
            )
            self.assertEqual(fanfic_info.title, "Story Title")


if __name__ == "__main__":
    unittest.main()
