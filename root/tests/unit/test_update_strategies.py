import unittest
from unittest.mock import MagicMock, call, patch

from calibre_integration import update_strategies, calibredb_utils
from models import fanfic_info, config_models
from models.context import WorkerContext
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

        self.mock_notification = MagicMock(
            spec=notification_wrapper.NotificationWrapper
        )
        self.retry_config = config_models.RetryConfig()

    # --- AddFormatStrategy Tests ---

    @patch(
        "calibre_integration.update_strategies.ff_logging.is_verbose", return_value=True
    )
    def test_add_format_success_verbose(self, mock_verbose):
        strategy = update_strategies.AddFormatStrategy()

        # Setup mocks
        old_metadata = {"title": "Old Title"}
        new_metadata = {"title": "Old Title", "date": "2023"}
        self.mock_client.get_metadata.side_effect = [old_metadata, new_metadata]
        self.mock_client.add_format_to_existing_story.return_value = True

        success, error_msg = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            self.path_or_url,
        )

        self.assertTrue(success)
        self.assertIsNone(error_msg)
        self.mock_client.get_metadata.assert_has_calls(
            [call(self.fanfic), call(self.fanfic)]
        )
        self.mock_client.add_format_to_existing_story.assert_called_once_with(
            self.temp_dir, self.fanfic
        )
        self.mock_client.log_metadata_comparison.assert_called_once_with(
            self.fanfic, old_metadata, new_metadata
        )

    @patch(
        "calibre_integration.update_strategies.ff_logging.is_verbose",
        return_value=False,
    )
    def test_add_format_success_non_verbose(self, mock_verbose):
        """In non-verbose mode, get_metadata should not be called (perf optimization)."""
        strategy = update_strategies.AddFormatStrategy()

        self.mock_client.add_format_to_existing_story.return_value = True

        success, error_msg = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            self.path_or_url,
        )

        self.assertTrue(success)
        self.assertIsNone(error_msg)
        self.mock_client.get_metadata.assert_not_called()
        self.mock_client.log_metadata_comparison.assert_not_called()
        self.mock_client.add_format_to_existing_story.assert_called_once()

    def test_add_format_failure(self):
        strategy = update_strategies.AddFormatStrategy()

        # Setup mocks
        self.mock_client.get_metadata.return_value = {}
        self.mock_client.add_format_to_existing_story.return_value = False

        success, error_msg = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            self.path_or_url,
        )

        self.assertFalse(success)
        self.assertEqual(error_msg, f"Failed to replace format for {self.path_or_url}")
        self.mock_client.add_format_to_existing_story.assert_called_once()

    # --- PreserveMetadataStrategy Tests ---

    @patch(
        "calibre_integration.update_strategies.ff_logging.is_verbose", return_value=True
    )
    def test_preserve_metadata_success_with_metadata_verbose(self, mock_verbose):
        strategy = update_strategies.PreserveMetadataStrategy()

        # Setup mocks: first call is pre-removal (always), second is post-restore (verbose)
        old_metadata = {"#custom": "value", "title": "Old"}
        new_metadata = {"#custom": "value", "title": "New"}
        self.mock_client.get_metadata.side_effect = [old_metadata, new_metadata]
        self.mock_client.get_story_id.return_value = "124"  # New ID

        success, error_msg = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            self.path_or_url,
        )

        self.assertTrue(success)
        self.assertIsNone(error_msg)
        # get_metadata called twice: once for restoration, once for verbose comparison
        self.assertEqual(self.mock_client.get_metadata.call_count, 2)
        self.mock_client.remove_story.assert_called_once_with(self.fanfic)
        self.mock_client.add_story.assert_called_once_with(
            location=self.temp_dir, fanfic=self.fanfic
        )
        self.mock_client.set_metadata_fields.assert_called_once_with(
            self.fanfic, old_metadata
        )
        self.mock_client.log_metadata_comparison.assert_called_once()

    @patch(
        "calibre_integration.update_strategies.ff_logging.is_verbose",
        return_value=False,
    )
    def test_preserve_metadata_success_with_metadata_non_verbose(self, mock_verbose):
        """Non-verbose: pre-removal get_metadata still called (needed for restoration), but post-restore comparison skipped."""
        strategy = update_strategies.PreserveMetadataStrategy()

        old_metadata = {"#custom": "value", "title": "Old"}
        self.mock_client.get_metadata.return_value = old_metadata
        self.mock_client.get_story_id.return_value = "124"

        success, error_msg = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            self.path_or_url,
        )

        self.assertTrue(success)
        self.assertIsNone(error_msg)
        # get_metadata called only once (pre-removal for restoration)
        self.mock_client.get_metadata.assert_called_once_with(self.fanfic)
        self.mock_client.set_metadata_fields.assert_called_once_with(
            self.fanfic, old_metadata
        )
        # Verbose comparison skipped
        self.mock_client.log_metadata_comparison.assert_not_called()

    def test_preserve_metadata_success_no_metadata(self):
        strategy = update_strategies.PreserveMetadataStrategy()

        self.mock_client.get_metadata.return_value = {}
        self.mock_client.get_story_id.return_value = "124"

        success, error_msg = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            self.path_or_url,
        )

        self.assertTrue(success)
        self.assertIsNone(error_msg)
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

        success, error_msg = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            self.path_or_url,
        )

        self.assertFalse(success)
        self.assertEqual(error_msg, f"Failed to add {self.path_or_url} to Calibre")
        self.mock_client.remove_story.assert_called_once()
        self.mock_client.add_story.assert_called_once()

    # --- RemoveAddStrategy Tests ---

    @patch(
        "calibre_integration.update_strategies.ff_logging.is_verbose", return_value=True
    )
    def test_remove_add_success_verbose(self, mock_verbose):
        strategy = update_strategies.RemoveAddStrategy()

        old_metadata = {"title": "Old"}
        new_metadata = {"title": "New"}
        self.mock_client.get_metadata.side_effect = [old_metadata, new_metadata]

        # Side effect: remove_story should clear calibre_id
        def remove_side_effect(fanfic):
            fanfic.calibre_id = None

        self.mock_client.remove_story.side_effect = remove_side_effect

        self.mock_client.get_story_id.return_value = "125"

        success, error_msg = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            self.path_or_url,
        )

        self.assertTrue(success)
        self.assertIsNone(error_msg)
        self.mock_client.remove_story.assert_called_once_with(self.fanfic)
        self.mock_client.add_story.assert_called_once()
        self.mock_client.log_metadata_comparison.assert_called_once()

    @patch(
        "calibre_integration.update_strategies.ff_logging.is_verbose",
        return_value=False,
    )
    def test_remove_add_success_non_verbose(self, mock_verbose):
        """Non-verbose: get_metadata not called at all (remove_add doesn't preserve metadata)."""
        strategy = update_strategies.RemoveAddStrategy()

        def remove_side_effect(fanfic):
            fanfic.calibre_id = None

        self.mock_client.remove_story.side_effect = remove_side_effect
        self.mock_client.get_story_id.return_value = "125"

        success, error_msg = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            self.path_or_url,
        )

        self.assertTrue(success)
        self.assertIsNone(error_msg)
        self.mock_client.get_metadata.assert_not_called()
        self.mock_client.log_metadata_comparison.assert_not_called()

    def test_remove_add_failure(self):
        strategy = update_strategies.RemoveAddStrategy()

        self.mock_client.get_metadata.return_value = {}

        # Side effect: remove_story should clear calibre_id
        def remove_side_effect(fanfic):
            fanfic.calibre_id = None

        self.mock_client.remove_story.side_effect = remove_side_effect

        self.mock_client.get_story_id.return_value = None

        success, error_msg = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            self.path_or_url,
        )

        self.assertFalse(success)
        self.assertEqual(error_msg, f"Failed to add {self.path_or_url} to Calibre")

    # --- AddNewStoryStrategy Tests ---

    def test_add_new_story_success(self):
        strategy = update_strategies.AddNewStoryStrategy()

        # New story has no ID initially
        self.fanfic.calibre_id = None

        # Simulate add_story populating the ID (optimization)
        def add_story_side_effect(location, fanfic):
            fanfic.calibre_id = "126"

        self.mock_client.add_story.side_effect = add_story_side_effect

        success, error_msg = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            self.path_or_url,
        )

        self.assertTrue(success)
        self.assertIsNone(error_msg)
        self.mock_client.add_story.assert_called_once_with(
            location=self.temp_dir, fanfic=self.fanfic
        )
        # Verify optimization: get_story_id should NOT be called if ID is already set
        self.mock_client.get_story_id.assert_not_called()

    def test_add_new_story_failure(self):
        strategy = update_strategies.AddNewStoryStrategy()

        # New story has no ID initially
        self.fanfic.calibre_id = None

        self.mock_client.get_story_id.return_value = None

        success, error_msg = strategy.execute(
            self.fanfic,
            self.mock_client,
            self.temp_dir,
            self.path_or_url,
        )

        self.assertFalse(success)
        self.assertEqual(error_msg, f"Failed to add {self.path_or_url} to Calibre")
        self.mock_client.add_story.assert_called_once()

    def test_process_fanfic_addition_with_real_strategy_and_history_recorder(self):
        """process_fanfic_addition + real strategy + HistoryRecorder records Calibre failure reason and retry event."""
        from queue import Queue
        from history.recorder import HistoryRecorder
        from workers import handlers

        history_q = Queue()
        recorder = HistoryRecorder(history_q)
        waiting_q = Queue()
        ingress_q = Queue()

        self.mock_client.cdb_info.metadata_preservation_mode = (
            config_models.MetadataPreservationMode.ADD_FORMAT
        )
        self.mock_client.add_format_to_existing_story.return_value = False

        ctx = WorkerContext(
            calibre_client=self.mock_client,
            notification_info=self.mock_notification,
            ingress_queue=ingress_q,
            waiting_queue=waiting_q,
            retry_config=self.retry_config,
            history_recorder=recorder,
            active_urls={},
        )

        should_remove = handlers.process_fanfic_addition(
            self.fanfic,
            ctx,
            self.temp_dir,
            self.path_or_url,
        )

        # Since retry was scheduled, URL should NOT be removed from active_urls
        self.assertFalse(should_remove)
        # Fanfic should be queued onto waiting_q with retry decision
        queued_fanfic = waiting_q.get_nowait()
        self.assertEqual(queued_fanfic.url, self.fanfic.url)
        self.assertIsNotNone(queued_fanfic.retry_decision)
        self.assertEqual(queued_fanfic.retry_decision.action.value, "retry")

        # HistoryRecorder queue should have retry_scheduled and download_updated (waiting)
        events = []
        while not history_q.empty():
            events.append(history_q.get_nowait())
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event_type"], "retry")
        self.assertIn("Failed to replace format", events[0]["payload"]["error_message"])
        self.assertEqual(events[1]["event_type"], "download_updated")
        self.assertEqual(events[1]["payload"]["status"], "waiting")
        self.assertIn("Failed to replace format", events[1]["payload"]["error_message"])
