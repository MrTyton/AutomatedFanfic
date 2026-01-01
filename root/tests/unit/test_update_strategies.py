import unittest
from unittest.mock import MagicMock, call
import multiprocessing as mp

from calibre_integration import update_strategies, calibredb_utils
from models import fanfic_info, config_models
from notifications import notification_wrapper


class TestUpdateStrategies(unittest.TestCase):
    def setUp(self):
        # Common setup
        self.fanfic = fanfic_info.FanficInfo(
            url="http://example.com/story", site="site", title="Test Story"
        )
        self.fanfic.calibre_id = "123"

        self.mock_client = MagicMock(spec=calibredb_utils.CalibreDBClient)
        self.mock_client.cdb_info = MagicMock()

        self.temp_dir = "/tmp/test"
        self.path_or_url = "/tmp/test/story.epub"

        self.mock_queue = MagicMock(spec=mp.Queue)
        self.mock_notification = MagicMock(
            spec=notification_wrapper.NotificationWrapper
        )
        self.retry_config = config_models.RetryConfig()

        self.mock_failure_handler = MagicMock()

    # --- AddFormatStrategy Tests ---

    def test_add_format_success(self):
        strategy = update_strategies.AddFormatStrategy()

        # Setup mocks
        old_metadata = {"title": "Old Title"}
        new_metadata = {"title": "Old Title", "date": "2023"}
        self.mock_client.get_metadata.side_effect = [old_metadata, new_metadata]
        self.mock_client.add_format_to_existing_story.return_value = True

        result = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            "site",
            self.path_or_url,
            self.mock_queue,
            self.mock_notification,
            self.retry_config,
            self.mock_failure_handler,
        )

        self.assertTrue(result)
        self.mock_client.get_metadata.assert_has_calls(
            [call(self.fanfic), call(self.fanfic)]
        )
        self.mock_client.add_format_to_existing_story.assert_called_once_with(
            self.temp_dir, self.fanfic
        )
        self.mock_client.log_metadata_comparison.assert_called_once_with(
            self.fanfic, old_metadata, new_metadata
        )
        self.mock_failure_handler.assert_not_called()

    def test_add_format_failure(self):
        strategy = update_strategies.AddFormatStrategy()

        # Setup mocks
        self.mock_client.get_metadata.return_value = {}
        self.mock_client.add_format_to_existing_story.return_value = False

        result = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            "site",
            self.path_or_url,
            self.mock_queue,
            self.mock_notification,
            self.retry_config,
            self.mock_failure_handler,
        )

        self.assertFalse(result)
        self.mock_client.add_format_to_existing_story.assert_called_once()
        self.mock_failure_handler.assert_called_once_with(
            self.fanfic,
            self.mock_notification,
            self.mock_queue,
            self.retry_config,
            self.mock_client.cdb_info,
        )

    # --- PreserveMetadataStrategy Tests ---

    def test_preserve_metadata_success_with_metadata(self):
        strategy = update_strategies.PreserveMetadataStrategy()

        # Setup mocks
        old_metadata = {"#custom": "value", "title": "Old"}
        new_metadata = {"#custom": "value", "title": "New"}
        self.mock_client.get_metadata.side_effect = [old_metadata, new_metadata]
        self.mock_client.get_story_id.return_value = "124"  # New ID

        result = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            "site",
            self.path_or_url,
            self.mock_queue,
            self.mock_notification,
            self.retry_config,
            self.mock_failure_handler,
        )

        self.assertTrue(result)
        self.mock_client.get_metadata.assert_called_with(self.fanfic)
        self.mock_client.remove_story.assert_called_once_with(self.fanfic)
        self.mock_client.add_story.assert_called_once_with(
            location=self.temp_dir, fanfic=self.fanfic
        )
        self.mock_client.set_metadata_fields.assert_called_once_with(
            self.fanfic, old_metadata
        )
        self.mock_client.log_metadata_comparison.assert_called_once()

    def test_preserve_metadata_success_no_metadata(self):
        strategy = update_strategies.PreserveMetadataStrategy()

        self.mock_client.get_metadata.return_value = {}
        self.mock_client.get_story_id.return_value = "124"

        result = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            "site",
            self.path_or_url,
            self.mock_queue,
            self.mock_notification,
            self.retry_config,
            self.mock_failure_handler,
        )

        self.assertTrue(result)
        self.mock_client.remove_story.assert_called_once()
        self.mock_client.add_story.assert_called_once()
        self.mock_client.set_metadata_fields.assert_not_called()

    def test_preserve_metadata_add_failure(self):
        strategy = update_strategies.PreserveMetadataStrategy()

        self.mock_client.get_metadata.return_value = {}

        # Side effect: remove_story should clear calibre_id (simulating real behavior)
        def remove_side_effect(fanfic):
            fanfic.calibre_id = None

        self.mock_client.remove_story.side_effect = remove_side_effect

        self.mock_client.get_story_id.return_value = None  # Failed to find ID after add

        result = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            "site",
            self.path_or_url,
            self.mock_queue,
            self.mock_notification,
            self.retry_config,
            self.mock_failure_handler,
        )

        self.assertFalse(result)
        self.mock_client.remove_story.assert_called_once()
        self.mock_client.add_story.assert_called_once()
        self.mock_failure_handler.assert_called_once()

    # --- RemoveAddStrategy Tests ---

    def test_remove_add_success(self):
        strategy = update_strategies.RemoveAddStrategy()

        old_metadata = {"title": "Old"}
        new_metadata = {"title": "New"}
        self.mock_client.get_metadata.side_effect = [old_metadata, new_metadata]

        # Side effect: remove_story should clear calibre_id
        def remove_side_effect(fanfic):
            fanfic.calibre_id = None

        self.mock_client.remove_story.side_effect = remove_side_effect

        self.mock_client.get_story_id.return_value = "125"

        result = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            "site",
            self.path_or_url,
            self.mock_queue,
            self.mock_notification,
            self.retry_config,
            self.mock_failure_handler,
        )

        self.assertTrue(result)
        self.mock_client.remove_story.assert_called_once_with(self.fanfic)
        self.mock_client.add_story.assert_called_once()
        self.mock_client.log_metadata_comparison.assert_called_once()

    def test_remove_add_failure(self):
        strategy = update_strategies.RemoveAddStrategy()

        self.mock_client.get_metadata.return_value = {}

        # Side effect: remove_story should clear calibre_id
        def remove_side_effect(fanfic):
            fanfic.calibre_id = None

        self.mock_client.remove_story.side_effect = remove_side_effect

        self.mock_client.get_story_id.return_value = None

        result = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            "site",
            self.path_or_url,
            self.mock_queue,
            self.mock_notification,
            self.retry_config,
            self.mock_failure_handler,
        )

        self.assertFalse(result)
        self.mock_failure_handler.assert_called_once()

    # --- AddNewStoryStrategy Tests ---

    def test_add_new_story_success(self):
        strategy = update_strategies.AddNewStoryStrategy()

        # New story has no ID initially
        self.fanfic.calibre_id = None

        # Simulate add_story populating the ID (optimization)
        def add_story_side_effect(location, fanfic):
            fanfic.calibre_id = "126"

        self.mock_client.add_story.side_effect = add_story_side_effect

        result = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            "site",
            self.path_or_url,
            self.mock_queue,
            self.mock_notification,
            self.retry_config,
            self.mock_failure_handler,
        )

        self.assertTrue(result)
        self.mock_client.add_story.assert_called_once_with(
            location=self.temp_dir, fanfic=self.fanfic
        )
        # Verify optimization: get_story_id should NOT be called if ID is already set
        self.mock_client.get_story_id.assert_not_called()
        self.mock_failure_handler.assert_not_called()

    def test_add_new_story_failure(self):
        strategy = update_strategies.AddNewStoryStrategy()

        # New story has no ID initially
        self.fanfic.calibre_id = None

        self.mock_client.get_story_id.return_value = None

        result = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            "site",
            self.path_or_url,
            self.mock_queue,
            self.mock_notification,
            self.retry_config,
            self.mock_failure_handler,
        )

        self.assertFalse(result)
        self.mock_client.add_story.assert_called_once()
        self.mock_failure_handler.assert_called_once()
