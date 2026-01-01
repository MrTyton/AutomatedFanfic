import unittest
from unittest.mock import MagicMock, patch
from workers import handlers
from models import fanfic_info, config_models
from calibre_integration import calibredb_utils
from notifications import notification_wrapper
import multiprocessing as mp


class TestHandlersNotification(unittest.TestCase):
    def setUp(self):
        self.mock_fanfic = MagicMock(spec=fanfic_info.FanficInfo)
        self.mock_fanfic.title = "Test Story"
        self.mock_fanfic.url = "http://example.com/story"
        self.mock_fanfic.site = "site"

        self.mock_client = MagicMock(spec=calibredb_utils.CalibreDBClient)
        self.mock_client.cdb_info = MagicMock()

        self.mock_notification = MagicMock(
            spec=notification_wrapper.NotificationWrapper
        )
        self.mock_queue = MagicMock(spec=mp.Queue)
        self.mock_config = MagicMock(spec=config_models.RetryConfig)

    @patch("workers.handlers.update_strategies")
    @patch("workers.handlers.ff_logging")
    def test_notification_sent_on_success_added(self, mock_logging, mock_strategies):
        """Test notification sent when story is successfully added (new)."""
        # Setup
        self.mock_client.get_story_id.return_value = None  # New story

        mock_strategy_instance = MagicMock()
        mock_strategy_instance.execute.return_value = True  # Success
        mock_strategies.AddNewStoryStrategy.return_value = mock_strategy_instance

        # Execute
        handlers.process_fanfic_addition(
            self.mock_fanfic,
            self.mock_client,
            "/temp/dir",
            "site",
            "http://example.com/story",
            self.mock_queue,
            self.mock_notification,
            self.mock_config,
        )

        # Verify
        self.mock_notification.send_notification.assert_called_once()
        args = self.mock_notification.send_notification.call_args[0]
        self.assertEqual(args[0], "New Fanfiction Download")  # Legacy Title behavior

    @patch("workers.handlers.update_strategies")
    @patch("workers.handlers.ff_logging")
    def test_notification_sent_on_success_updated(self, mock_logging, mock_strategies):
        """Test notification sent when story is successfully updated (existing)."""
        # Setup
        self.mock_client.get_story_id.return_value = "123"  # Existing story
        # Configure strategy to return success
        mock_strategy_instance = MagicMock()
        mock_strategy_instance.execute.return_value = True

        # We need to mock the strategy selection logic or just ensure whatever is picked returns true
        # In this case handlers picks based on config, let's just make ALL strategies return the mock
        mock_strategies.AddFormatStrategy.return_value = mock_strategy_instance
        mock_strategies.PreserveMetadataStrategy.return_value = mock_strategy_instance
        mock_strategies.RemoveAddStrategy.return_value = mock_strategy_instance

        # Execute
        handlers.process_fanfic_addition(
            self.mock_fanfic,
            self.mock_client,
            "/temp/dir",
            "site",
            "http://example.com/story",
            self.mock_queue,
            self.mock_notification,
            self.mock_config,
        )

        # Verify
        self.mock_notification.send_notification.assert_called_once()
        args = self.mock_notification.send_notification.call_args[0]
        self.assertEqual(args[0], "New Fanfiction Download")  # Legacy Title behavior

    @patch("workers.handlers.update_strategies")
    @patch("workers.handlers.ff_logging")
    def test_no_notification_on_failure(self, mock_logging, mock_strategies):
        """Test NO notification sent when strategy fails."""
        # Setup
        self.mock_client.get_story_id.return_value = None

        mock_strategy_instance = MagicMock()
        mock_strategy_instance.execute.return_value = False  # Failure
        mock_strategies.AddNewStoryStrategy.return_value = mock_strategy_instance

        # Execute
        handlers.process_fanfic_addition(
            self.mock_fanfic,
            self.mock_client,
            "/temp/dir",
            "site",
            "http://example.com/story",
            self.mock_queue,
            self.mock_notification,
            self.mock_config,
        )

        # Verify
        self.mock_notification.send_notification.assert_not_called()
