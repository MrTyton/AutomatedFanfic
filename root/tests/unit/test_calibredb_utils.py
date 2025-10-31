import unittest
import subprocess
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
    get_calibre_version,
    get_metadata,
    set_metadata_fields,
    log_metadata_comparison,
    add_format_to_existing_story,
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
                expected_command='add -d "/fake/location/story.epub"',
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
                expected_command,
                calibre_info,
                fanfic_info=None,
            )
            self.assertEqual(fanfic_info.title, "Story Title")


class GetCalibreVersionTestCase(unittest.TestCase):
    """Test cases for get_calibre_version function."""

    @parameterized.expand(
        [
            (
                "windows_calibre_version",
                b"calibredb.exe (calibre 8.4)\n",
                "8.4",
            ),
            (
                "linux_calibre_version",
                b"calibredb (calibre 6.29.0)\n",
                "6.29.0",
            ),
            (
                "minimal_version",
                b"calibredb (calibre 5.0)\n",
                "5.0",
            ),
            (
                "beta_version",
                b"calibredb (calibre 7.15.1)\n",
                "7.15.1",
            ),
        ]
    )
    @patch("subprocess.check_output")
    def test_get_calibre_version_success(
        self, name, mock_output, expected_version, mock_check_output
    ):
        """Test successful Calibre version extraction with various output formats."""
        mock_check_output.return_value = mock_output

        result = get_calibre_version()

        self.assertEqual(result, expected_version)
        mock_check_output.assert_called_once_with(
            ["calibredb", "--version"], stderr=subprocess.DEVNULL, timeout=10
        )

    @parameterized.expand(
        [
            (
                "file_not_found",
                FileNotFoundError("calibredb not found"),
                "Error: calibredb not found",
            ),
            (
                "timeout_error",
                subprocess.TimeoutExpired("calibredb", 10),
                "Error: Command 'calibredb' timed out after 10 seconds",
            ),
            (
                "generic_exception",
                Exception("Something went wrong"),
                "Error: Something went wrong",
            ),
        ]
    )
    @patch("subprocess.check_output")
    def test_get_calibre_version_errors(
        self, name, mock_exception, expected_message, mock_check_output
    ):
        """Test error handling for various failure scenarios."""
        mock_check_output.side_effect = mock_exception

        result = get_calibre_version()

        self.assertEqual(result, expected_message)

    @parameterized.expand(
        [
            (
                "unexpected_format",
                b"Some unexpected output\n",
                "Some unexpected output",
            ),
            (
                "no_calibre_keyword",
                b"version 8.4\n",
                "version 8.4",
            ),
            (
                "empty_output",
                b"",
                "",
            ),
        ]
    )
    @patch("subprocess.check_output")
    def test_get_calibre_version_unexpected_format(
        self, name, mock_output, expected_result, mock_check_output
    ):
        """Test handling of unexpected output formats."""
        mock_check_output.return_value = mock_output

        result = get_calibre_version()

        self.assertEqual(result, expected_result)


class GetMetadataTestCase(unittest.TestCase):
    """Tests for the get_metadata function."""

    @patch("subprocess.check_output")
    def test_get_metadata_success(self, mock_check_output):
        """Test successful metadata retrieval."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"

        mock_cdb = MagicMock()
        mock_cdb.lock = MagicMock()

        # Mock JSON output from calibredb
        mock_output = b"""[{
            "id": 123,
            "title": "Test Story",
            "authors": ["Test Author"],
            "#mytag": "custom value",
            "#status": "Complete"
        }]"""

        mock_check_output.return_value = mock_output

        result = get_metadata(mock_fanfic, mock_cdb)

        self.assertIsInstance(result, dict)
        self.assertEqual(result["id"], 123)
        self.assertEqual(result["title"], "Test Story")
        self.assertEqual(result["#mytag"], "custom value")
        self.assertEqual(result["#status"], "Complete")

    @patch("subprocess.check_output")
    def test_get_metadata_no_calibre_id(self, mock_check_output):
        """Test that function returns empty dict when no calibre_id."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = None

        mock_cdb = MagicMock()

        result = get_metadata(mock_fanfic, mock_cdb)

        self.assertEqual(result, {})
        mock_check_output.assert_not_called()

    @patch("subprocess.check_output")
    def test_get_metadata_empty_result(self, mock_check_output):
        """Test handling of empty metadata list."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"

        mock_cdb = MagicMock()
        mock_cdb.lock = MagicMock()

        mock_check_output.return_value = b"[]"

        result = get_metadata(mock_fanfic, mock_cdb)

        self.assertEqual(result, {})

    @patch("subprocess.check_output")
    def test_get_metadata_json_decode_error(self, mock_check_output):
        """Test handling of invalid JSON."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"

        mock_cdb = MagicMock()
        mock_cdb.lock = MagicMock()

        mock_check_output.return_value = b"invalid json{"

        result = get_metadata(mock_fanfic, mock_cdb)

        self.assertEqual(result, {})

    @patch("subprocess.check_output")
    def test_get_metadata_subprocess_error(self, mock_check_output):
        """Test handling of subprocess errors."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"

        mock_cdb = MagicMock()
        mock_cdb.lock = MagicMock()

        mock_check_output.side_effect = subprocess.CalledProcessError(1, "cmd")

        result = get_metadata(mock_fanfic, mock_cdb)

        self.assertEqual(result, {})


class SetMetadataFieldsTestCase(unittest.TestCase):
    """Tests for the set_metadata_fields function."""

    @patch("calibredb_utils.call_calibre_db")
    def test_set_metadata_fields_success(self, mock_call_calibre_db):
        """Test successful metadata field restoration."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"

        mock_cdb = MagicMock()
        mock_cdb.lock = MagicMock()

        old_metadata = {
            "id": 456,  # Old ID, should be different
            "title": "Test Story",
            "#mytag": "custom value",
            "#status": "Complete",
            "#rating": "5 stars",
        }

        set_metadata_fields(mock_fanfic, mock_cdb, old_metadata)

        # Should be called 3 times, once for each custom field
        self.assertEqual(mock_call_calibre_db.call_count, 3)

        # Verify the commands are properly formatted
        calls = mock_call_calibre_db.call_args_list
        for call in calls:
            command = call[0][0]
            self.assertTrue(command.startswith("set_custom "))

    @patch("calibredb_utils.call_calibre_db")
    def test_set_metadata_fields_no_custom_fields(self, mock_call_calibre_db):
        """Test with no custom fields to restore."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"

        mock_cdb = MagicMock()
        mock_cdb.lock = MagicMock()

        old_metadata = {"id": 456, "title": "Test Story", "authors": ["Test Author"]}

        set_metadata_fields(mock_fanfic, mock_cdb, old_metadata)

        # Should not be called since there are no custom fields
        mock_call_calibre_db.assert_not_called()

    @patch("calibredb_utils.call_calibre_db")
    def test_set_metadata_fields_empty_metadata(self, mock_call_calibre_db):
        """Test with empty metadata."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123

        mock_cdb = MagicMock()

        set_metadata_fields(mock_fanfic, mock_cdb, {})

        mock_call_calibre_db.assert_not_called()

    @patch("calibredb_utils.call_calibre_db")
    def test_set_metadata_fields_subprocess_error(self, mock_call_calibre_db):
        """Test handling of subprocess errors."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"

        mock_cdb = MagicMock()
        mock_cdb.lock = MagicMock()

        old_metadata = {"#mytag": "custom value"}

        mock_call_calibre_db.side_effect = subprocess.CalledProcessError(1, "cmd")

        # Should not raise exception, just log error
        set_metadata_fields(mock_fanfic, mock_cdb, old_metadata)

        # Should have attempted the call
        self.assertEqual(mock_call_calibre_db.call_count, 1)


class LogMetadataComparisonTestCase(unittest.TestCase):
    """Tests for the log_metadata_comparison function."""

    @patch("ff_logging.log_debug")
    @patch("ff_logging.log")
    def test_log_metadata_comparison_no_changes(self, mock_log, mock_log_debug):
        """Test logging when fields are unchanged."""
        mock_fanfic = MagicMock()
        mock_fanfic.site = "fanfiction.net"

        old_metadata = {"#mytag": "custom value", "#status": "Complete"}
        new_metadata = {"#mytag": "custom value", "#status": "Complete"}

        log_metadata_comparison(mock_fanfic, old_metadata, new_metadata)

        # Should log no changes detected (debug only)
        calls = [str(call) for call in mock_log_debug.call_args_list]
        self.assertTrue(any("No metadata changes detected" in call for call in calls))
        # Should NOT use regular log
        self.assertEqual(mock_log.call_count, 0)

    @patch("ff_logging.log_debug")
    @patch("ff_logging.log")
    def test_log_metadata_comparison_changed_fields(self, mock_log, mock_log_debug):
        """Test logging when fields change."""
        mock_fanfic = MagicMock()
        mock_fanfic.site = "fanfiction.net"

        old_metadata = {"#mytag": "old value", "#status": "In Progress"}
        new_metadata = {"#mytag": "new value", "#status": "Complete"}

        log_metadata_comparison(mock_fanfic, old_metadata, new_metadata)

        # Should log changed fields count (debug only)
        calls = [str(call) for call in mock_log_debug.call_args_list]
        self.assertTrue(any("Fields Changed: 2" in call for call in calls))
        # Should NOT use regular log
        self.assertEqual(mock_log.call_count, 0)

    @patch("ff_logging.log_debug")
    @patch("ff_logging.log")
    def test_log_metadata_comparison_lost_fields(self, mock_log, mock_log_debug):
        """Test logging when fields are lost."""
        mock_fanfic = MagicMock()
        mock_fanfic.site = "fanfiction.net"

        old_metadata = {"#mytag": "custom value", "#status": "Complete"}
        new_metadata = {}

        log_metadata_comparison(mock_fanfic, old_metadata, new_metadata)

        # Should log lost fields count (debug only)
        calls = [str(call) for call in mock_log_debug.call_args_list]
        self.assertTrue(any("Fields Lost: 2" in call for call in calls))
        # Should NOT use regular log
        self.assertEqual(mock_log.call_count, 0)

    @patch("ff_logging.log_debug")
    @patch("ff_logging.log")
    def test_log_metadata_comparison_empty_metadata(self, mock_log, mock_log_debug):
        """Test with both metadata dicts empty."""
        mock_fanfic = MagicMock()
        mock_fanfic.site = "fanfiction.net"

        log_metadata_comparison(mock_fanfic, {}, {})

        # Should call log_debug for "No metadata to compare"
        self.assertGreater(mock_log_debug.call_count, 0)
        # Should NOT use regular log
        self.assertEqual(mock_log.call_count, 0)


class AddFormatToExistingStoryTestCase(unittest.TestCase):
    """Tests for the add_format_to_existing_story function."""

    @patch("calibredb_utils.call_calibre_db")
    @patch("system_utils.get_files")
    def test_add_format_success(self, mock_get_files, mock_call_calibre_db):
        """Test successful format addition."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"

        mock_cdb = MagicMock()
        mock_cdb.lock = MagicMock()

        # Mock the get_files to return a fake EPUB file
        mock_get_files.return_value = ["/fake/dir/story.epub"]

        result = add_format_to_existing_story("/fake/dir", mock_fanfic, mock_cdb)

        self.assertTrue(result)
        mock_call_calibre_db.assert_called_once()

        # Verify the command contains the right components
        call_args = mock_call_calibre_db.call_args[0]
        command = call_args[0]
        calibre_info = call_args[1]
        fanfic_info = call_args[2]

        self.assertIn("add_format", command)
        self.assertIn("--replace", command)
        self.assertEqual(fanfic_info, mock_fanfic)
        self.assertEqual(calibre_info, mock_cdb)

    @patch("system_utils.get_files")
    def test_add_format_no_calibre_id(self, mock_get_files):
        """Test that function fails when no calibre_id."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = None

        mock_cdb = MagicMock()

        result = add_format_to_existing_story("/fake/dir", mock_fanfic, mock_cdb)

        self.assertFalse(result)
        mock_get_files.assert_not_called()

    @patch("calibredb_utils.call_calibre_db")
    @patch("system_utils.get_files")
    def test_add_format_subprocess_error(self, mock_get_files, mock_call_calibre_db):
        """Test handling of subprocess errors."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"

        mock_cdb = MagicMock()
        mock_cdb.lock = MagicMock()

        # Mock the get_files to return a fake EPUB file
        mock_get_files.return_value = ["/fake/dir/story.epub"]

        # Mock the call to fail
        mock_call_calibre_db.side_effect = Exception("Command failed")

        result = add_format_to_existing_story("/fake/dir", mock_fanfic, mock_cdb)

        self.assertFalse(result)

    @patch("system_utils.get_files")
    def test_add_format_no_epub_files(self, mock_get_files):
        """Test handling when no EPUB files found."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"

        mock_cdb = MagicMock()
        mock_cdb.lock = MagicMock()

        # Mock get_files to return empty list
        mock_get_files.return_value = []

        result = add_format_to_existing_story("/fake/dir", mock_fanfic, mock_cdb)

        self.assertFalse(result)


class TestLogMetadataComparison(unittest.TestCase):
    """Test suite for log_metadata_comparison function."""

    def setUp(self):
        """Set up test fixtures."""
        self.fanfic = MagicMock()
        self.fanfic.site = "ao3"

    @patch("calibredb_utils.ff_logging")
    def test_both_empty_metadata(self, mock_logging):
        """Test comparison with both old and new metadata empty."""
        log_metadata_comparison(self.fanfic, {}, {})

        # Should log that there's no metadata to compare
        calls = [str(call) for call in mock_logging.log_debug.call_args_list]
        self.assertTrue(any("No metadata to compare" in call for call in calls))

    @patch("calibredb_utils.ff_logging")
    def test_no_changes(self, mock_logging):
        """Test when all fields are unchanged."""
        old_meta = {
            "title": "Test Story",
            "authors": ["Author Name"],
            "#custom1": "custom value",
            "#rating": "Teen",
        }
        new_meta = {
            "title": "Test Story",
            "authors": ["Author Name"],
            "#custom1": "custom value",
            "#rating": "Teen",
        }

        log_metadata_comparison(self.fanfic, old_meta, new_meta)

        debug_calls = [str(call) for call in mock_logging.log_debug.call_args_list]
        # Should report no changes (debug only)
        self.assertTrue(
            any("No metadata changes detected" in call for call in debug_calls)
        )
        # Should NOT use regular log
        self.assertEqual(mock_logging.log.call_count, 0)

    @patch("calibredb_utils.ff_logging")
    def test_fields_changed(self, mock_logging):
        """Test when fields are changed."""
        old_meta = {
            "title": "Old Title",
            "authors": ["Old Author"],
            "#status": "In Progress",
        }
        new_meta = {
            "title": "New Title",
            "authors": ["New Author"],
            "#status": "Complete",
        }

        log_metadata_comparison(self.fanfic, old_meta, new_meta)

        debug_calls = [str(call) for call in mock_logging.log_debug.call_args_list]

        # Should report fields changed (debug only)
        self.assertTrue(any("Fields Changed: 3" in call for call in debug_calls))

        # Should show all changed fields
        self.assertTrue(
            any(
                "title" in call and "Old Title" in call and "New Title" in call
                for call in debug_calls
            )
        )
        self.assertTrue(any("authors" in call for call in debug_calls))
        self.assertTrue(
            any(
                "#status" in call and "In Progress" in call and "Complete" in call
                for call in debug_calls
            )
        )

        # Should NOT use regular log
        self.assertEqual(mock_logging.log.call_count, 0)

    @patch("calibredb_utils.ff_logging")
    def test_fields_lost(self, mock_logging):
        """Test when fields are lost during update."""
        old_meta = {
            "title": "Story Title",
            "#custom1": "value1",
            "#custom2": "value2",
            "series": "Series Name",
        }
        new_meta = {
            "title": "Story Title",
            "series": "Series Name",
        }

        log_metadata_comparison(self.fanfic, old_meta, new_meta)

        debug_calls = [str(call) for call in mock_logging.log_debug.call_args_list]

        # Should report fields lost (debug only)
        self.assertTrue(any("Fields Lost: 2" in call for call in debug_calls))

        # Should show all lost fields
        self.assertTrue(any("#custom1" in call for call in debug_calls))
        self.assertTrue(any("#custom2" in call for call in debug_calls))

        # Should NOT use regular log
        self.assertEqual(mock_logging.log.call_count, 0)

    @patch("calibredb_utils.ff_logging")
    def test_new_fields_added(self, mock_logging):
        """Test when new fields are added."""
        old_meta = {
            "title": "Story Title",
        }
        new_meta = {
            "title": "Story Title",
            "#new_field": "new value",
            "publisher": "FanFicFare",
        }

        log_metadata_comparison(self.fanfic, old_meta, new_meta)

        debug_calls = [str(call) for call in mock_logging.log_debug.call_args_list]

        # Should report new fields added (debug only)
        self.assertTrue(any("New Fields Added: 2" in call for call in debug_calls))

        # Should show all new fields
        self.assertTrue(any("#new_field" in call for call in debug_calls))
        self.assertTrue(any("publisher" in call for call in debug_calls))

        # Should NOT use regular log
        self.assertEqual(mock_logging.log.call_count, 0)

    @patch("calibredb_utils.ff_logging")
    def test_mixed_changes(self, mock_logging):
        """Test with mix of changed, lost, and new fields."""
        old_meta = {
            "title": "Title",
            "authors": ["Author"],
            "#custom1": "value1",
            "tags": ["tag1"],
        }
        new_meta = {
            "title": "New Title",  # Changed
            "authors": ["Author"],  # Same (not logged)
            "#custom1": "new_value1",  # Changed
            "publisher": "New Field",  # New
            # tags lost
        }

        log_metadata_comparison(self.fanfic, old_meta, new_meta)

        debug_calls = [str(call) for call in mock_logging.log_debug.call_args_list]

        # Should report all change types (debug only)
        self.assertTrue(any("Fields Changed: 2" in call for call in debug_calls))
        self.assertTrue(any("Fields Lost: 1" in call for call in debug_calls))
        self.assertTrue(any("New Fields Added: 1" in call for call in debug_calls))

        # Should NOT report preserved fields
        self.assertFalse(
            any("No metadata changes detected" in call for call in debug_calls)
        )

        # Should NOT use regular log
        self.assertEqual(mock_logging.log.call_count, 0)

    @patch("calibredb_utils.ff_logging")
    def test_many_changed_fields_all_shown(self, mock_logging):
        """Test that all changed fields are shown without truncation."""
        # Create many changed fields
        old_meta = {f"field{i}": f"old{i}" for i in range(20)}
        new_meta = {f"field{i}": f"new{i}" for i in range(20)}

        log_metadata_comparison(self.fanfic, old_meta, new_meta)

        debug_calls = [str(call) for call in mock_logging.log_debug.call_args_list]

        # Should show all 20 changes (debug only)
        self.assertTrue(any("Fields Changed: 20" in call for call in debug_calls))

        # Should NOT have truncation messages
        self.assertFalse(any("and" in call and "more" in call for call in debug_calls))

        # Verify all fields are present
        for i in range(20):
            self.assertTrue(any(f"field{i}" in call for call in debug_calls))

        # Should NOT use regular log
        self.assertEqual(mock_logging.log.call_count, 0)

    @patch("calibredb_utils.ff_logging")
    def test_many_lost_fields_all_shown(self, mock_logging):
        """Test that all lost fields are shown without truncation."""
        # Create many lost fields
        old_meta = {f"#field{i}": f"value{i}" for i in range(15)}
        new_meta = {}

        log_metadata_comparison(self.fanfic, old_meta, new_meta)

        debug_calls = [str(call) for call in mock_logging.log_debug.call_args_list]

        # Should show all 15 lost fields (debug only)
        self.assertTrue(any("Fields Lost: 15" in call for call in debug_calls))

        # Should NOT have truncation messages
        self.assertFalse(any("and" in call and "more" in call for call in debug_calls))

        # Verify all fields are present
        for i in range(15):
            self.assertTrue(any(f"#field{i}" in call for call in debug_calls))

        # Should NOT use regular log
        self.assertEqual(mock_logging.log.call_count, 0)

    @patch("calibredb_utils.ff_logging")
    def test_value_truncation(self, mock_logging):
        """Test that long values are truncated to 50 characters."""
        old_meta = {
            "description": "A" * 100,
        }
        new_meta = {
            "description": "B" * 100,
        }

        log_metadata_comparison(self.fanfic, old_meta, new_meta)

        debug_calls = [str(call) for call in mock_logging.log_debug.call_args_list]

        # Should truncate to 50 characters
        truncated_old = "A" * 50
        truncated_new = "B" * 50

        self.assertTrue(
            any(truncated_old in call and truncated_new in call for call in debug_calls)
        )

        # Should NOT use regular log
        self.assertEqual(mock_logging.log.call_count, 0)


if __name__ == "__main__":
    unittest.main()
