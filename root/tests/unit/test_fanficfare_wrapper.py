"""
Test cases for the FanFicFare native API wrapper.

This module tests the new native Python API wrapper that replaces
CLI subprocess calls with direct FanFicFare API usage.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock, call
import tempfile
import os
from typing import Dict, Any

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

    @patch('fanficfare_wrapper.os.chdir')
    @patch('fanficfare_wrapper.cli.get_configuration')
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

    @patch('fanficfare_wrapper.os.chdir')
    @patch('fanficfare_wrapper.cli.get_configuration')
    def test_create_configuration_with_ini_files(self, mock_get_config, mock_chdir):
        """Test configuration creation with existing INI files."""
        mock_config = Mock()
        mock_get_config.return_value = mock_config
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock INI files
            personal_ini = os.path.join(temp_dir, "personal.ini")
            defaults_ini = os.path.join(temp_dir, "defaults.ini")
            
            with open(personal_ini, 'w') as f:
                f.write("[personal]\ntest=value\n")
            with open(defaults_ini, 'w') as f:
                f.write("[defaults]\nother=setting\n")
            
            result = fanficfare_wrapper.create_configuration(
                self.test_url, temp_dir, self.mock_cdb
            )
            
            self.assertEqual(result, mock_config)
            # Check that configuration was called with INI content
            call_args = mock_get_config.call_args
            self.assertIsNotNone(call_args[0][1])  # passed_defaults
            self.assertIsNotNone(call_args[0][2])  # passed_personal

    @patch('fanficfare_wrapper.os.chdir')
    @patch('fanficfare_wrapper.cli.get_configuration')
    @patch('fanficfare_wrapper.adapters.get_url_chapter_range')
    @patch('fanficfare_wrapper.adapters.getAdapter')
    @patch('fanficfare_wrapper.cli.write_story')
    def test_execute_fanficfare_success_new_story(
        self, mock_write_story, mock_get_adapter, mock_get_range, 
        mock_get_config, mock_chdir
    ):
        """Test successful execution for a new story."""
        # Setup mocks
        mock_config = Mock()
        mock_get_config.return_value = mock_config
        
        mock_get_range.return_value = (self.test_url, None, None)
        
        mock_adapter = Mock()
        mock_story_metadata = Mock()
        mock_story_metadata.getAllMetadata.return_value = {"numChapters": 5, "title": "Test Story"}
        mock_adapter.getStoryMetadataOnly.return_value = mock_story_metadata
        mock_adapter.story.chapter_error_count = 0
        mock_get_adapter.return_value = mock_adapter
        
        mock_write_story.return_value = "/tmp/test_story.epub"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            result = fanficfare_wrapper.execute_fanficfare(
                self.test_url, temp_dir, self.mock_cdb
            )
            
            self.assertTrue(result.success)
            self.assertEqual(result.output_filename, "/tmp/test_story.epub")
            self.assertEqual(result.chapter_count, 5)
            self.assertIsNotNone(result.metadata)

    @patch('fanficfare_wrapper.os.chdir')
    @patch('fanficfare_wrapper.cli.get_configuration')
    @patch('fanficfare_wrapper.adapters.get_url_chapter_range')
    @patch('fanficfare_wrapper.adapters.getAdapter')
    def test_execute_fanficfare_invalid_url(
        self, mock_get_adapter, mock_get_range, mock_get_config, mock_chdir
    ):
        """Test execution with invalid URL."""
        from fanficfare.exceptions import InvalidStoryURL
        
        mock_config = Mock()
        mock_get_config.return_value = mock_config
        
        mock_get_range.return_value = (self.test_url, None, None)
        mock_get_adapter.side_effect = InvalidStoryURL(self.test_url, "example.com", "https://example.com/story/123")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            result = fanficfare_wrapper.execute_fanficfare(
                self.test_url, temp_dir, self.mock_cdb
            )
            
            self.assertFalse(result.success)
            self.assertIn("Invalid story URL", result.error_message)
            self.assertIsInstance(result.exception, InvalidStoryURL)

    @patch('fanficfare_wrapper.os.chdir')
    @patch('fanficfare_wrapper.cli.get_configuration')
    @patch('fanficfare_wrapper.adapters.get_url_chapter_range')
    @patch('fanficfare_wrapper.adapters.getAdapter')
    def test_execute_fanficfare_story_not_exist(
        self, mock_get_adapter, mock_get_range, mock_get_config, mock_chdir
    ):
        """Test execution when story does not exist."""
        from fanficfare.exceptions import StoryDoesNotExist
        
        mock_config = Mock()
        mock_get_config.return_value = mock_config
        
        mock_get_range.return_value = (self.test_url, None, None)
        mock_get_adapter.side_effect = StoryDoesNotExist(self.test_url)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            result = fanficfare_wrapper.execute_fanficfare(
                self.test_url, temp_dir, self.mock_cdb
            )
            
            self.assertFalse(result.success)
            self.assertIn("Story does not exist", result.error_message)
            self.assertIsInstance(result.exception, StoryDoesNotExist)

    @patch('fanficfare_wrapper.os.chdir')
    @patch('fanficfare_wrapper.cli.get_configuration')
    @patch('fanficfare_wrapper.adapters.get_url_chapter_range')
    @patch('fanficfare_wrapper.adapters.getAdapter')
    def test_execute_fanficfare_access_denied(
        self, mock_get_adapter, mock_get_range, mock_get_config, mock_chdir
    ):
        """Test execution when access is denied."""
        from fanficfare.exceptions import AccessDenied
        
        mock_config = Mock()
        mock_get_config.return_value = mock_config
        
        mock_get_range.return_value = (self.test_url, None, None)
        mock_get_adapter.side_effect = AccessDenied("Access denied")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            result = fanficfare_wrapper.execute_fanficfare(
                self.test_url, temp_dir, self.mock_cdb
            )
            
            self.assertFalse(result.success)
            self.assertIn("Access denied", result.error_message)
            self.assertIsInstance(result.exception, AccessDenied)

    @patch('fanficfare_wrapper.os.chdir')
    @patch('fanficfare_wrapper.cli.get_configuration')
    @patch('fanficfare_wrapper.adapters.get_url_chapter_range')
    @patch('fanficfare_wrapper.adapters.getAdapter')
    @patch('fanficfare_wrapper.cli.write_story')
    def test_execute_fanficfare_chapter_errors(
        self, mock_write_story, mock_get_adapter, mock_get_range, 
        mock_get_config, mock_chdir
    ):
        """Test execution when some chapters fail to download."""
        mock_config = Mock()
        mock_get_config.return_value = mock_config
        
        mock_get_range.return_value = (self.test_url, None, None)
        
        mock_adapter = Mock()
        mock_story_metadata = Mock()
        mock_story_metadata.getAllMetadata.return_value = {"numChapters": 5}
        mock_adapter.getStoryMetadataOnly.return_value = mock_story_metadata
        mock_adapter.story.chapter_error_count = 2  # Some chapters failed
        mock_get_adapter.return_value = mock_adapter
        
        mock_write_story.return_value = "/tmp/test_story.epub"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            result = fanficfare_wrapper.execute_fanficfare(
                self.test_url, temp_dir, self.mock_cdb
            )
            
            self.assertFalse(result.success)
            self.assertIn("chapters errored downloading", result.error_message)
            self.assertEqual(result.output_filename, "/tmp/test_story.epub")

    @patch('fanficfare_wrapper.os.path.exists')
    @patch('fanficfare_wrapper.os.chdir')
    @patch('fanficfare_wrapper.cli.get_dcsource_chaptercount')
    @patch('fanficfare_wrapper.cli.get_configuration')
    @patch('fanficfare_wrapper.adapters.get_url_chapter_range')
    @patch('fanficfare_wrapper.adapters.getAdapter')
    def test_execute_fanficfare_update_same_chapters(
        self, mock_get_adapter, mock_get_range, mock_get_config,
        mock_get_chapters, mock_chdir, mock_exists
    ):
        """Test update when story already has same number of chapters."""
        # Setup for update scenario
        epub_path = "/tmp/existing_story.epub"  
        mock_exists.return_value = True
        mock_get_chapters.return_value = (self.test_url, 5)  # 5 existing chapters
        
        mock_config = Mock()
        mock_get_config.return_value = mock_config
        
        mock_get_range.return_value = (self.test_url, None, None)
        
        mock_adapter = Mock()
        mock_story_metadata = Mock()
        mock_story_metadata.getChapterCount.return_value = 5  # Same as existing
        mock_adapter.getStoryMetadataOnly.return_value = mock_story_metadata
        mock_get_adapter.return_value = mock_adapter
        
        with tempfile.TemporaryDirectory() as temp_dir:
            result = fanficfare_wrapper.execute_fanficfare(
                epub_path, temp_dir, self.mock_cdb,
                force=False, update_always=False  # Make sure we trigger the "same chapters" logic
            )
            
            self.assertTrue(result.success)
            self.assertIn("already contains 5 chapters", result.output_text)
            self.assertEqual(result.chapter_count, 5)

    def test_fanficfare_result_dataclass(self):
        """Test FanFicFareResult dataclass functionality."""
        # Test successful result
        result = fanficfare_wrapper.FanFicFareResult(
            success=True,
            output_filename="/tmp/story.epub",
            chapter_count=10
        )
        
        self.assertTrue(result.success)
        self.assertEqual(result.output_filename, "/tmp/story.epub")
        self.assertEqual(result.chapter_count, 10)
        self.assertIsNone(result.error_message)
        
        # Test failed result
        error_result = fanficfare_wrapper.FanFicFareResult(
            success=False,
            error_message="Test error",
            exception=RuntimeError("Test exception")
        )
        
        self.assertFalse(error_result.success)
        self.assertEqual(error_result.error_message, "Test error")
        self.assertIsInstance(error_result.exception, RuntimeError)


if __name__ == '__main__':
    unittest.main()