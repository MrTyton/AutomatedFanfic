import unittest
from unittest.mock import MagicMock, patch
from workers import handlers
from models import fanfic_info, config_models
from models.context import WorkerContext
from calibre_integration import calibredb_utils
from notifications import notification_wrapper
import multiprocessing as mp


class TestHandlersNotification(unittest.TestCase):
    def setUp(self):
        self.mock_fanfic = fanfic_info.FanficInfo(
            url="http://example.com/story", site="site", title="Test Story"
        )

        self.mock_client = MagicMock(spec=calibredb_utils.CalibreDBClient)
        self.mock_client.cdb_info = MagicMock()

        self.mock_notification = MagicMock(
            spec=notification_wrapper.NotificationWrapper
        )
        self.mock_ingress_queue = MagicMock(spec=mp.Queue)
        self.mock_queue = MagicMock(spec=mp.Queue)
        self.mock_config = MagicMock(spec=config_models.RetryConfig)
        self.ctx = WorkerContext(
            calibre_client=self.mock_client,
            notification_info=self.mock_notification,
            ingress_queue=self.mock_ingress_queue,
            waiting_queue=self.mock_queue,
            retry_config=self.mock_config,
        )

    @patch("workers.handlers.update_strategies")
    @patch("workers.handlers.ff_logging")
    def test_notification_sent_on_success_added(self, mock_logging, mock_strategies):
        """Test notification sent when story is successfully added (new)."""
        self.mock_client.get_story_id.return_value = None  # New story

        mock_strategy_instance = MagicMock()
        mock_strategy_instance.execute.return_value = (True, None)
        mock_strategies.AddNewStoryStrategy.return_value = mock_strategy_instance

        handlers.process_fanfic_addition(
            self.mock_fanfic,
            self.ctx,
            "/temp/dir",
            "http://example.com/story",
        )

        self.mock_notification.send_notification.assert_called_once()
        args = self.mock_notification.send_notification.call_args[0]
        self.assertEqual(args[0], "New Fanfiction Download")

    @patch("workers.handlers.update_strategies")
    @patch("workers.handlers.ff_logging")
    def test_notification_sent_on_success_updated(self, mock_logging, mock_strategies):
        """Test notification sent when story is successfully updated (existing)."""
        self.mock_fanfic.calibre_id = "123"
        mock_strategy_instance = MagicMock()
        mock_strategy_instance.execute.return_value = (True, None)

        mock_strategies.AddFormatStrategy.return_value = mock_strategy_instance
        mock_strategies.PreserveMetadataStrategy.return_value = mock_strategy_instance
        mock_strategies.RemoveAddStrategy.return_value = mock_strategy_instance

        handlers.process_fanfic_addition(
            self.mock_fanfic,
            self.ctx,
            "/temp/dir",
            "http://example.com/story",
        )

        self.mock_notification.send_notification.assert_called_once()
        args = self.mock_notification.send_notification.call_args[0]
        self.assertEqual(args[0], "New Fanfiction Download")

    @patch("workers.handlers.handle_failure")
    @patch("workers.handlers.update_strategies")
    @patch("workers.handlers.ff_logging")
    def test_no_notification_on_failure_and_calls_handle_failure(
        self, mock_logging, mock_strategies, mock_handle_failure
    ):
        """Test NO success notification sent when strategy fails, and handle_failure is invoked."""
        self.mock_client.get_story_id.return_value = None

        mock_strategy_instance = MagicMock()
        mock_strategy_instance.execute.return_value = (False, "Calibre add failed")
        mock_strategies.AddNewStoryStrategy.return_value = mock_strategy_instance

        handlers.process_fanfic_addition(
            self.mock_fanfic,
            self.ctx,
            "/temp/dir",
            "http://example.com/story",
        )

        self.mock_notification.send_notification.assert_not_called()
        mock_handle_failure.assert_called_once_with(
            self.mock_fanfic,
            self.ctx,
            error_message="Calibre add failed",
        )
