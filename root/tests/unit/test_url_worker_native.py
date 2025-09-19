"""
Additional test cases for the native FanFicFare integration in url_worker.

This module tests the new execute_fanficfare_native function and integration
with the existing url_worker functionality.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import tempfile

import url_worker
import fanficfare_wrapper
import calibre_info
import fanfic_info


class TestUrlWorkerNativeIntegration(unittest.TestCase):
    """Test cases for native FanFicFare integration in url_worker."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_cdb = Mock(spec=calibre_info.CalibreInfo)
        self.mock_cdb.update_method = "update"
        
        self.mock_fanfic = Mock(spec=fanfic_info.FanficInfo)
        self.mock_fanfic.behavior = None
        self.mock_fanfic.url = "https://example.com/story/123"
        
        self.test_path_or_url = "https://example.com/story/123"
        self.test_temp_dir = "/tmp/test_work"

    @patch('url_worker.fanficfare_wrapper.execute_fanficfare')
    @patch('url_worker.fanficfare_wrapper.get_update_mode_params')
    def test_execute_fanficfare_native_success(self, mock_get_params, mock_execute):
        """Test successful execution of native FanFicFare API."""
        # Setup mocks
        mock_get_params.return_value = ("update", False, False)
        
        mock_result = fanficfare_wrapper.FanFicFareResult(
            success=True,
            output_filename="/tmp/story.epub",
            chapter_count=5
        )
        mock_execute.return_value = mock_result
        
        # Execute
        result = url_worker.execute_fanficfare_native(
            self.mock_cdb, self.mock_fanfic, self.test_path_or_url, self.test_temp_dir
        )
        
        # Verify
        self.assertTrue(result.success)
        self.assertEqual(result.output_filename, "/tmp/story.epub")
        self.assertEqual(result.chapter_count, 5)
        
        mock_get_params.assert_called_once_with("update", False)
        mock_execute.assert_called_once_with(
            url_or_path=self.test_path_or_url,
            work_dir=self.test_temp_dir,
            cdb=self.mock_cdb,
            update_mode="update",
            force=False,
            update_always=False,
            update_cover=True
        )

    @patch('url_worker.fanficfare_wrapper.execute_fanficfare')
    @patch('url_worker.fanficfare_wrapper.get_update_mode_params')
    def test_execute_fanficfare_native_force_behavior(self, mock_get_params, mock_execute):
        """Test native execution with force behavior."""
        # Setup for force behavior
        self.mock_fanfic.behavior = "force"
        mock_get_params.return_value = ("force", True, False)
        
        mock_result = fanficfare_wrapper.FanFicFareResult(success=True)
        mock_execute.return_value = mock_result
        
        # Execute
        result = url_worker.execute_fanficfare_native(
            self.mock_cdb, self.mock_fanfic, self.test_path_or_url, self.test_temp_dir
        )
        
        # Verify force behavior was detected
        mock_get_params.assert_called_once_with("update", True)
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        self.assertTrue(call_args.kwargs['force'])

    @patch('url_worker.fanficfare_wrapper.execute_fanficfare')
    @patch('url_worker.fanficfare_wrapper.get_update_mode_params')
    def test_execute_fanficfare_native_update_no_force(self, mock_get_params, mock_execute):
        """Test native execution with update_no_force method."""
        # Setup for update_no_force
        self.mock_cdb.update_method = "update_no_force"
        self.mock_fanfic.behavior = "force"  # Should be ignored
        mock_get_params.return_value = ("update", False, False)
        
        mock_result = fanficfare_wrapper.FanFicFareResult(success=True)
        mock_execute.return_value = mock_result
        
        # Execute
        result = url_worker.execute_fanficfare_native(
            self.mock_cdb, self.mock_fanfic, self.test_path_or_url, self.test_temp_dir
        )
        
        # Verify force was ignored
        mock_get_params.assert_called_once_with("update_no_force", True)
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        self.assertFalse(call_args.kwargs['force'])

    @patch('url_worker.fanficfare_wrapper.execute_fanficfare')
    @patch('url_worker.fanficfare_wrapper.get_update_mode_params')
    def test_execute_fanficfare_native_failure(self, mock_get_params, mock_execute):
        """Test native execution with failure result."""
        mock_get_params.return_value = ("update", False, False)
        
        mock_result = fanficfare_wrapper.FanFicFareResult(
            success=False,
            error_message="Test error message"
        )
        mock_execute.return_value = mock_result
        
        # Execute
        result = url_worker.execute_fanficfare_native(
            self.mock_cdb, self.mock_fanfic, self.test_path_or_url, self.test_temp_dir
        )
        
        # Verify failure
        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "Test error message")

    @patch('url_worker.fanficfare_wrapper.execute_fanficfare')
    @patch('url_worker.fanficfare_wrapper.get_update_mode_params')
    def test_execute_fanficfare_native_update_always(self, mock_get_params, mock_execute):
        """Test native execution with update_always method."""
        self.mock_cdb.update_method = "update_always"
        mock_get_params.return_value = ("update", False, True)
        
        mock_result = fanficfare_wrapper.FanFicFareResult(success=True)
        mock_execute.return_value = mock_result
        
        # Execute
        result = url_worker.execute_fanficfare_native(
            self.mock_cdb, self.mock_fanfic, self.test_path_or_url, self.test_temp_dir
        )
        
        # Verify update_always was set
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        self.assertTrue(call_args.kwargs['update_always'])

    def test_legacy_execute_command_still_works(self):
        """Test that legacy execute_command function still works for backward compatibility."""
        with patch('url_worker.check_output') as mock_check_output:
            mock_check_output.return_value = b"test output"
            
            result = url_worker.execute_command("echo test")
            
            self.assertEqual(result, "test output")
            mock_check_output.assert_called_once_with(
                "echo test", shell=True, stderr=url_worker.STDOUT, stdin=url_worker.PIPE
            )

    def test_legacy_construct_fanficfare_command_still_works(self):
        """Test that legacy construct_fanficfare_command function still works."""
        result = url_worker.construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.test_path_or_url
        )
        
        expected = f'python -m fanficfare.cli -u "{self.test_path_or_url}" --update-cover --non-interactive'
        self.assertEqual(result, expected)

    def test_legacy_construct_fanficfare_command_force(self):
        """Test legacy construct_fanficfare_command with force behavior."""
        self.mock_fanfic.behavior = "force"
        
        result = url_worker.construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.test_path_or_url
        )
        
        expected = f'python -m fanficfare.cli --force "{self.test_path_or_url}" --update-cover --non-interactive'
        self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()