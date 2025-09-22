"""
Test cases for the FanFicFare native API wrapper.

This module tests the new native Python API wrapper that replaces
CLI subprocess calls with direct FanFicFare API usage.
"""

import unittest
from unittest.mock import Mock, patch
import tempfile
import os

import fanficfare_wrapper
import calibre_info
import fanfic_info


class TestFanFicFareWrapper(unittest.TestCase):
    """Test cases for FanFicFare native API wrapper functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_cdb = Mock(spec=calibre_info.CalibreInfo)
        self.mock_cdb.update_method = "update"

        self.mock_fanfic = Mock(spec=fanfic_info.FanficInfo)
        self.mock_fanfic.behavior = None
        self.mock_fanfic.url = "https://example.com/story/123"

        self.test_url = "https://example.com/story/123"
        self.test_work_dir = "/tmp/test_work"

    def test_get_update_mode_params_update(self):
        """Test update mode parameter conversion for normal update."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "update", False
        )

        self.assertEqual(update_mode, "update")
        self.assertFalse(force)
        self.assertFalse(update_always)

    def test_get_update_mode_params_force_requested(self):
        """Test update mode parameter conversion when force is requested."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "update", True
        )

        self.assertEqual(update_mode, "force")
        self.assertTrue(force)
        self.assertFalse(update_always)

    def test_get_update_mode_params_update_always(self):
        """Test update mode parameter conversion for update_always."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "update_always", False
        )

        self.assertEqual(update_mode, "update")
        self.assertFalse(force)
        self.assertTrue(update_always)

    def test_get_update_mode_params_force_method(self):
        """Test update mode parameter conversion for force method."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "force", False
        )

        self.assertEqual(update_mode, "force")
        self.assertTrue(force)
        self.assertFalse(update_always)

    def test_get_update_mode_params_update_no_force(self):
        """Test update mode parameter conversion for update_no_force."""
        update_mode, force, update_always = fanficfare_wrapper.get_update_mode_params(
            "update_no_force", True  # Force requested but should be ignored
        )

        self.assertEqual(update_mode, "update")
        self.assertFalse(force)  # Force should be ignored
        self.assertFalse(update_always)

    @patch("fanficfare_wrapper.os.chdir")
    @patch("fanficfare_wrapper.cli.get_configuration")
    def test_create_configuration_basic(self, mock_get_config, mock_chdir):
        """Test basic configuration creation."""
        mock_config = Mock()
        mock_get_config.return_value = mock_config

        with tempfile.TemporaryDirectory() as temp_dir:
            result = fanficfare_wrapper.create_configuration(
                self.test_url, temp_dir, self.mock_cdb
            )

            self.assertEqual(result, mock_config)
            mock_get_config.assert_called_once()

    @patch("fanficfare_wrapper.os.chdir")
    @patch("fanficfare_wrapper.cli.get_configuration")
    def test_create_configuration_with_ini_files(self, mock_get_config, mock_chdir):
        """Test configuration creation with existing INI files."""
        mock_config = Mock()
        mock_get_config.return_value = mock_config

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock INI files
            personal_ini = os.path.join(temp_dir, "personal.ini")
            defaults_ini = os.path.join(temp_dir, "defaults.ini")

            with open(personal_ini, "w") as f:
                f.write("[personal]\ntest=value\n")
            with open(defaults_ini, "w") as f:
                f.write("[defaults]\nother=setting\n")

            result = fanficfare_wrapper.create_configuration(
                self.test_url, temp_dir, self.mock_cdb
            )

            self.assertEqual(result, mock_config)
            # Check that configuration was called with INI content
            call_args = mock_get_config.call_args
            self.assertIsNotNone(call_args[0][1])  # passed_defaults
            self.assertIsNotNone(call_args[0][2])  # passed_personal

    def test_fanficfare_result_dataclass(self):
        """Test FanFicFareResult dataclass functionality."""
        # Test successful result
        result = fanficfare_wrapper.FanFicFareResult(
            success=True, output_filename="/tmp/story.epub", chapter_count=10
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output_filename, "/tmp/story.epub")
        self.assertEqual(result.chapter_count, 10)
        self.assertIsNone(result.error_message)

        # Test failed result
        error_result = fanficfare_wrapper.FanFicFareResult(
            success=False,
            error_message="Test error",
            exception=RuntimeError("Test exception"),
        )

        self.assertFalse(error_result.success)
        self.assertEqual(error_result.error_message, "Test error")
        self.assertIsInstance(error_result.exception, RuntimeError)


if __name__ == "__main__":
    unittest.main()
