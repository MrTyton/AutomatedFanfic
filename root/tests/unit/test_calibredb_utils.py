import unittest
import subprocess
from unittest.mock import MagicMock, patch
from parameterized import parameterized
from typing import NamedTuple, Optional

from models import fanfic_info
from calibre_integration import calibre_info
from calibre_integration.calibredb_utils import CalibreDBClient


class TestCalibreDBClient(unittest.TestCase):
    def setUp(self):
        """Set up commonly used mocks."""
        self.mock_calibre_info = MagicMock(spec=calibre_info.CalibreInfo)
        self.mock_calibre_info.lock = MagicMock()
        self.client = CalibreDBClient(self.mock_calibre_info)

    class ExecuteCommandParams(NamedTuple):
        command: str
        fanfic: Optional[fanfic_info.FanficInfo]
        expected_command: str
        should_raise_exception: bool

    @parameterized.expand(
        [
            ExecuteCommandParams(
                command="list",
                fanfic=None,
                expected_command="list ",
                should_raise_exception=False,
            ),
            ExecuteCommandParams(
                command="add",
                fanfic=MagicMock(calibre_id="123"),
                expected_command="add 123",
                should_raise_exception=False,
            ),
            ExecuteCommandParams(
                command="remove",
                fanfic=MagicMock(calibre_id="123"),
                expected_command="remove 123",
                should_raise_exception=True,
            ),
        ]
    )
    @patch("calibre_integration.calibredb_utils.call", return_value=None)
    @patch("calibre_integration.calibredb_utils.ff_logging.log_failure")
    @patch("calibre_integration.calibredb_utils.ff_logging.log_debug")
    def test_execute_command(
        self,
        command,
        fanfic,
        expected_command,
        should_raise_exception,
        mock_log_debug,
        mock_log_failure,
        mock_call,
    ):
        """Test the internal _execute_command method."""
        if should_raise_exception:
            mock_call.side_effect = Exception("Test exception")

        # Accessing private method for testing purpose
        self.client._execute_command(command, fanfic)

        # The internal log uses {command_args} {id_str}
        id_str = fanfic.calibre_id if fanfic and fanfic.calibre_id else ""

        mock_log_debug.assert_called_once_with(
            f'\tCalling calibredb with command: \t"{command} {id_str}"'
        )

        if should_raise_exception:
            mock_log_failure.assert_called_once()
        else:
            mock_log_failure.assert_not_called()

    class ExportStoryParams(NamedTuple):
        fanfic: fanfic_info.FanficInfo
        location: str
        expected_command: str

    @parameterized.expand(
        [
            ExportStoryParams(
                fanfic=MagicMock(calibre_id="123"),
                location="/fake/location",
                expected_command='export 123 --dont-save-cover --dont-write-opf --single-dir --to-dir "/fake/location"',
            ),
        ]
    )
    def test_export_story(
        self,
        fanfic,
        location,
        expected_command,
    ):
        """Test export_story method."""
        with patch.object(self.client, "_execute_command") as mock_execute:
            self.client.export_story(fanfic, location)
            mock_execute.assert_called_once_with(expected_command, fanfic)

    class RemoveStoryParams(NamedTuple):
        fanfic: fanfic_info.FanficInfo
        expected_command: str

    @parameterized.expand(
        [
            RemoveStoryParams(
                fanfic=MagicMock(calibre_id="123"),
                expected_command="remove 123",
            ),
        ]
    )
    def test_remove_story(
        self,
        fanfic,
        expected_command,
    ):
        """Test remove_story method."""
        with patch.object(self.client, "_execute_command") as mock_execute:
            self.client.remove_story(fanfic)
            mock_execute.assert_called_once_with(expected_command, fanfic)

    class AddStoryParams(NamedTuple):
        location: str
        fanfic: fanfic_info.FanficInfo
        epub_files: list
        expected_command: str
        should_fail: bool

    @parameterized.expand(
        [
            AddStoryParams(
                location="/fake/location",
                fanfic=MagicMock(),
                epub_files=["/fake/location/story.epub"],
                expected_command='add -d "/fake/location/story.epub"',
                should_fail=False,
            ),
            AddStoryParams(
                location="/fake/location",
                fanfic=MagicMock(),
                epub_files=[],
                expected_command="",
                should_fail=True,
            ),
        ]
    )
    @patch("calibre_integration.calibredb_utils.system_utils.get_files")
    @patch(
        "calibre_integration.calibredb_utils.regex_parsing.extract_filename",
        return_value="Story Title",
    )
    @patch("calibre_integration.calibredb_utils.ff_logging.log_failure")
    @patch("calibre_integration.calibredb_utils.ff_logging.log")
    def test_add_story(
        self,
        location,
        fanfic,
        epub_files,
        expected_command,
        should_fail,
        mock_log,
        mock_log_failure,
        mock_extract_filename,
        mock_get_files,
    ):
        """Test add_story method."""
        mock_get_files.return_value = epub_files

        with patch.object(self.client, "_execute_command") as mock_execute:
            self.client.add_story(location, fanfic)

            if should_fail:
                mock_log_failure.assert_called_once_with(
                    "No EPUB files found in the specified location."
                )
                mock_execute.assert_not_called()
            else:
                mock_log.assert_called_once_with(
                    f"\t({fanfic.site}) Adding {epub_files[0]} to Calibre"
                )
                mock_execute.assert_called_once_with(
                    expected_command,
                    fanfic,
                )
                self.assertEqual(fanfic.title, "Story Title")

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
    @patch("calibre_integration.calibredb_utils.check_output")
    def test_get_calibre_version_success(
        self, name, mock_output, expected_version, mock_check_output
    ):
        """Test successful Calibre version extraction."""
        mock_check_output.return_value = mock_output
        result = self.client.get_calibre_version()
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
    @patch("calibre_integration.calibredb_utils.check_output")
    def test_get_calibre_version_errors(
        self, name, mock_exception, expected_message, mock_check_output
    ):
        """Test error handling for get_calibre_version."""
        mock_check_output.side_effect = mock_exception
        result = self.client.get_calibre_version()
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
    @patch("calibre_integration.calibredb_utils.check_output")
    def test_get_calibre_version_unexpected_format(
        self, name, mock_output, expected_result, mock_check_output
    ):
        """Test handling of unexpected output formats in get_calibre_version."""
        mock_check_output.return_value = mock_output
        result = self.client.get_calibre_version()
        self.assertEqual(result, expected_result)

    @patch("calibre_integration.calibredb_utils.check_output")
    def test_get_metadata_success(self, mock_check_output):
        """Test successful metadata retrieval."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"

        # Mock JSON output from calibredb
        mock_output = b"""[{
            "id": 123,
            "title": "Test Story",
            "authors": ["Test Author"],
            "#mytag": "custom value",
            "#status": "Complete"
        }]"""
        mock_check_output.return_value = mock_output

        result = self.client.get_metadata(mock_fanfic)

        self.assertIsInstance(result, dict)
        self.assertEqual(result["id"], 123)

    @patch("subprocess.check_output")
    def test_get_metadata_no_calibre_id(self, mock_check_output):
        """Test that function returns empty dict when no calibre_id."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = None

        result = self.client.get_metadata(mock_fanfic)

        self.assertEqual(result, {})
        mock_check_output.assert_not_called()

    @patch("subprocess.check_output")
    def test_get_metadata_empty_result(self, mock_check_output):
        """Test handling of empty metadata list."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"
        mock_check_output.return_value = b"[]"

        result = self.client.get_metadata(mock_fanfic)

        self.assertEqual(result, {})

    @patch("subprocess.check_output")
    def test_get_metadata_json_decode_error(self, mock_check_output):
        """Test handling of invalid JSON in get_metadata."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"
        mock_check_output.return_value = b"invalid json{"

        result = self.client.get_metadata(mock_fanfic)

        self.assertEqual(result, {})

    @patch("subprocess.check_output")
    def test_get_metadata_subprocess_error(self, mock_check_output):
        """Test handling of subprocess errors in get_metadata."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"
        mock_check_output.side_effect = subprocess.CalledProcessError(1, "cmd")

        result = self.client.get_metadata(mock_fanfic)

        self.assertEqual(result, {})

    def test_set_metadata_fields_success(self):
        """Test successful metadata field restoration."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"

        old_metadata = {
            "id": 456,  # Old ID, should be different
            "title": "Test Story",
            "#mytag": "custom value",
            "#status": "Complete",
            "#rating": "5 stars",
        }

        with patch.object(self.client, "_execute_command") as mock_execute:
            self.client.set_metadata_fields(mock_fanfic, old_metadata)

            # Should be called 3 times, once for each custom field
            self.assertEqual(mock_execute.call_count, 3)

            # Verify the calls
            calls = mock_execute.call_args_list
            for call_obj in calls:
                command = call_obj[0][0]  # first arg of call
                self.assertTrue(command.startswith("set_custom "))

    def test_set_metadata_fields_no_custom_fields(self):
        """Test with no custom fields to restore."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"
        old_metadata = {"id": 456, "title": "Test Story", "authors": ["Test Author"]}

        with patch.object(self.client, "_execute_command") as mock_execute:
            self.client.set_metadata_fields(mock_fanfic, old_metadata)
            mock_execute.assert_not_called()

    def test_set_metadata_fields_empty_metadata(self):
        """Test with empty metadata."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        with patch.object(self.client, "_execute_command") as mock_execute:
            self.client.set_metadata_fields(mock_fanfic, {})
            mock_execute.assert_not_called()

    @patch("calibre_integration.calibredb_utils.ff_logging.log_debug")
    @patch("calibre_integration.calibredb_utils.ff_logging.log")
    def test_log_metadata_comparison_no_changes(self, mock_log, mock_log_debug):
        """Test logging when fields are unchanged."""
        mock_fanfic = MagicMock()
        mock_fanfic.site = "fanfiction.net"
        old_metadata = {"#mytag": "val", "#status": "1"}
        new_metadata = {"#mytag": "val", "#status": "1"}

        self.client.log_metadata_comparison(mock_fanfic, old_metadata, new_metadata)

        # Implementation only logs the header if no changes
        mock_log_debug.assert_called_once_with(
            f"\t({mock_fanfic.site}) Metadata Comparison Report"
        )
        self.assertEqual(mock_log.call_count, 0)

    @patch("calibre_integration.calibredb_utils.ff_logging.log_debug")
    @patch("calibre_integration.calibredb_utils.ff_logging.log")
    def test_log_metadata_comparison_changed_fields(self, mock_log, mock_log_debug):
        """Test logging when fields change."""
        mock_fanfic = MagicMock()
        mock_fanfic.site = "fanfiction.net"
        old_metadata = {"#mytag": "old"}
        new_metadata = {"#mytag": "new", "#other": "val"}

        self.client.log_metadata_comparison(mock_fanfic, old_metadata, new_metadata)

        # Check that we logged the specific changes
        debug_calls = [str(call) for call in mock_log_debug.call_args_list]
        self.assertTrue(
            any("Fields Changed: 1" in call for call in debug_calls),
            f"Calls: {debug_calls}",
        )
        self.assertTrue(
            any("New Fields Added: 1" in call for call in debug_calls),
            f"Calls: {debug_calls}",
        )
        self.assertEqual(mock_log.call_count, 0)

    @patch("calibre_integration.calibredb_utils.ff_logging.log_debug")
    @patch("calibre_integration.calibredb_utils.ff_logging.log")
    def test_log_metadata_comparison_fields_lost(self, mock_log, mock_log_debug):
        """Test logging when fields are lost."""
        mock_fanfic = MagicMock()
        mock_fanfic.site = "fanfiction.net"
        old_metadata = {"#mytag": "val", "#deleted": "val"}
        new_metadata = {"#mytag": "val"}

        self.client.log_metadata_comparison(mock_fanfic, old_metadata, new_metadata)

        debug_calls = [str(call) for call in mock_log_debug.call_args_list]
        self.assertTrue(
            any("Fields Lost: 1" in call for call in debug_calls),
            f"Calls: {debug_calls}",
        )
        self.assertEqual(mock_log.call_count, 0)

    @patch("calibre_integration.calibredb_utils.ff_logging.log_debug")
    @patch("calibre_integration.calibredb_utils.ff_logging.log")
    def test_log_metadata_comparison_empty(self, mock_log, mock_log_debug):
        """Test logging when both metadata dicts are empty."""
        mock_fanfic = MagicMock()
        mock_fanfic.site = "fanfiction.net"

        self.client.log_metadata_comparison(mock_fanfic, {}, {})

        # Implementation returns early if both empty
        mock_log_debug.assert_not_called()

    @patch("utils.system_utils.get_files")
    def test_add_format_success(self, mock_get_files):
        """Test successful format addition."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"

        mock_get_files.return_value = ["/fake/dir/story.epub"]

        with patch.object(self.client, "_execute_command") as mock_execute:
            result = self.client.add_format_to_existing_story("/fake/dir", mock_fanfic)

            self.assertTrue(result)
            mock_execute.assert_called_once()

            call_args = mock_execute.call_args
            command = call_args[0][0]
            self.assertIn("add_format", command)
            self.assertIn("--replace", command)
            # fanfic object is passed as second arg
            self.assertEqual(call_args[0][1], mock_fanfic)

    @patch("utils.system_utils.get_files")
    def test_add_format_no_calibre_id(self, mock_get_files):
        """Test that function fails when no calibre_id."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = None

        result = self.client.add_format_to_existing_story("/fake/dir", mock_fanfic)

        self.assertFalse(result)
        mock_get_files.assert_not_called()

    @patch("utils.system_utils.get_files")
    def test_add_format_subprocess_error(self, mock_get_files):
        """Test handling of subprocess errors in add_format."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_fanfic.site = "fanfiction.net"
        mock_get_files.return_value = ["/fake/dir/story.epub"]

        with patch.object(self.client, "_execute_command") as mock_execute:
            mock_execute.side_effect = Exception("Command failed")
            result = self.client.add_format_to_existing_story("/fake/dir", mock_fanfic)
            self.assertFalse(result)

    @patch("utils.system_utils.get_files")
    def test_add_format_no_epub_files(self, mock_get_files):
        """Test handling when no EPUB files found."""
        mock_fanfic = MagicMock()
        mock_fanfic.calibre_id = 123
        mock_get_files.return_value = []

        result = self.client.add_format_to_existing_story("/fake/dir", mock_fanfic)

        self.assertFalse(result)

    @patch("calibre_integration.calibredb_utils.check_output")
    def test_get_story_id_success(self, mock_check_output):
        """Test successful story ID retrieval using search command."""
        mock_fanfic = MagicMock()
        mock_fanfic.url = "http://example.com/story"
        mock_fanfic.site = "site"

        # Mock search output: comma-separated list of IDs
        mock_check_output.return_value = b"123, 124\n"

        result = self.client.get_story_id(mock_fanfic)

        self.assertEqual(result, "123")
        self.assertEqual(mock_fanfic.calibre_id, "123")

        # Verify the command structure matches user request
        mock_check_output.assert_called_once()
        args = mock_check_output.call_args[0][0]  # First arg of call
        # Expected: calibredb search "Identifiers:http://example.com/story" ...
        self.assertIn("search", args)
        self.assertIn('"Identifiers:http://example.com/story"', args)

    @patch("calibre_integration.calibredb_utils.check_output")
    def test_get_story_id_not_found(self, mock_check_output):
        """Test story ID not found (empty output)."""
        mock_fanfic = MagicMock()
        mock_fanfic.url = "http://example.com/story"

        mock_check_output.return_value = b"\n"

        result = self.client.get_story_id(mock_fanfic)

        self.assertIsNone(result)

    @patch("calibre_integration.calibredb_utils.check_output")
    def test_get_story_id_error(self, mock_check_output):
        """Test error handling in get_story_id."""
        mock_fanfic = MagicMock()
        mock_fanfic.url = "http://example.com/story"

        mock_check_output.side_effect = Exception("Search failed")

        result = self.client.get_story_id(mock_fanfic)

        self.assertIsNone(result)
