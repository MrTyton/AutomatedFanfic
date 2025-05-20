import unittest
from unittest.mock import patch, mock_open, MagicMock
import tomllib
from apprise_notification import AppriseNotification
from notification_wrapper import NotificationWrapper
from parameterized import parameterized
import notification_base
import apprise_notification
import io

class TestAppriseNotification(unittest.TestCase):

    def _create_mock_tomllib_config(self, apprise_config=None, pushbullet_config=None):
        config_dict = {}
        if apprise_config is not None:
            config_dict["apprise"] = apprise_config
        if pushbullet_config is not None:
            config_dict["pushbullet"] = pushbullet_config
        return tomllib.dumps(config_dict)

    @patch("builtins.open", new_callable=mock_open)
    @patch("tomllib.load")
    def test_initialization_reads_urls(self, mock_tomllib_load, mock_file_open):
        mock_config = {
            "apprise": {
                "urls": ["url1", "url2"]
            }
        }
        mock_tomllib_load.return_value = mock_config
        
        # Patch apprise.Apprise globally for this test to inspect its instance
        with patch("apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = ["url1", "url2"] # Simulate successful add

            notifier = AppriseNotification("dummy_path.tomllib")
            
            self.assertTrue(notifier.enabled)
            # Check that Apprise object was populated
            mock_apprise_obj.add.assert_any_call("url1")
            mock_apprise_obj.add.assert_any_call("url2")
            self.assertIn("url1", notifier.apprise_urls) # Original list still kept
            self.assertIn("url2", notifier.apprise_urls)

        mock_file_open.assert_called_once_with("dummy_path.tomllib", "rb")

    @patch("builtins.open", new_callable=mock_open)
    @patch("tomllib.load")
    def test_initialization_missing_apprise_section(self, mock_tomllib_load, mock_file_open):
        mock_tomllib_load.return_value = {} # No 'apprise' section
        with patch("apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = [] # No URLs added

            notifier = AppriseNotification("dummy_path.tomllib")
            self.assertEqual(notifier.apprise_urls, set()) # Original list empty
            self.assertFalse(notifier.enabled) 
            mock_apprise_obj.add.assert_not_called()


    @patch("builtins.open", new_callable=mock_open)
    @patch("tomllib.load")
    def test_initialization_missing_urls_key(self, mock_tomllib_load, mock_file_open):
        mock_config = {"apprise": {}}
        mock_tomllib_load.return_value = mock_config
        with patch("apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = []

            notifier = AppriseNotification("dummy_path.tomllib")
            self.assertEqual(notifier.apprise_urls, set())
            self.assertFalse(notifier.enabled)
            mock_apprise_obj.add.assert_not_called()

    @patch("builtins.open", new_callable=mock_open)
    @patch("tomllib.load")
    def test_initialization_empty_urls_list(self, mock_tomllib_load, mock_file_open):
        mock_config = {"apprise": {"urls": []}}
        mock_tomllib_load.return_value = mock_config
        with patch("apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = []
            
            notifier = AppriseNotification("dummy_path.tomllib")
            self.assertEqual(notifier.apprise_urls, set())
            self.assertFalse(notifier.enabled)
            mock_apprise_obj.add.assert_not_called()


    # --- Tests for auto-addition of Pushbullet URL ---
    @patch("builtins.open", new_callable=mock_open)
    @patch("tomllib.load")
    @patch("apprise_notification.ff_logging")
    def test_init_auto_adds_pushbullet_url_no_device(self, mock_ff_logging, mock_tomllib_load, mock_file_open):
        mock_config = {
            "pushbullet": {"enabled": True, "api_key": "pb_api_key123"}
        }
        mock_tomllib_load.return_value = mock_config
        
        with patch("apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.add.return_value = True # Simulate successful add
            mock_apprise_obj.urls.return_value = ["pbul://pb_api_key123"]


            notifier = AppriseNotification("dummy_path.tomllib")

            self.assertTrue(notifier.enabled)
            expected_pb_url = "pbul://pb_api_key123"
            mock_apprise_obj.add.assert_called_once_with(expected_pb_url)
            self.assertIn(expected_pb_url, notifier.apprise_urls)
            mock_ff_logging.log_debug.assert_any_call(f"Automatically added Pushbullet URL to Apprise: {expected_pb_url}")

    @patch("builtins.open", new_callable=mock_open)
    @patch("tomllib.load")
    def test_init_pushbullet_disabled(self, mock_tomllib_load, mock_file_open):
        mock_config = {
            "pushbullet": {"enabled": False, "api_key": "pb_api_key"}
        }
        mock_tomllib_load.return_value = mock_config
        with patch("apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = []

            notifier = AppriseNotification("dummy_path.tomllib")
            self.assertFalse(notifier.enabled)
            # Check that no pbul URL was added to apprise_urls list or apobj
            self.assertEqual(notifier.apprise_urls, set())
            mock_apprise_obj.add.assert_not_called()

    @patch("builtins.open", new_callable=mock_open)
    @patch("tomllib.load")
    def test_init_pushbullet_no_api_key(self, mock_tomllib_load, mock_file_open):
        mock_config = {"pushbullet": {"enabled": True}} # No api_key
        mock_tomllib_load.return_value = mock_config
        with patch("apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = []

            notifier = AppriseNotification("dummy_path.tomllib")
            self.assertFalse(notifier.enabled)
            self.assertEqual(notifier.apprise_urls, set())
            mock_apprise_obj.add.assert_not_called()


    @patch("apprise_notification.apprise.Apprise")
    @patch("builtins.open", new_callable=mock_open)
    @patch("tomllib.load")
    @patch("apprise_notification.ff_logging")
    def test_send_notification_failure(self, mock_ff_logging, mock_tomllib_load, mock_file_open, MockAppriseClass):
        mock_apprise_obj_instance = MockAppriseClass.return_value
        mock_apprise_obj_instance.add.return_value = True
        mock_apprise_obj_instance.urls.return_value = ["url1"]
        mock_apprise_obj_instance.notify.return_value = False # Simulate Apprise failure

        mock_config = {"apprise": {"urls": ["url1"]}}
        # Patch time.sleep so retry_decorator doesn't actually sleep
        mock_tomllib_load.return_value = mock_config
        
        notifier = AppriseNotification("dummy_path.tomllib")
        self.assertTrue(notifier.enabled)

        with patch("notification_base.time.sleep", return_value=None):
            result = notifier.send_notification("Test Title", "Test Body", "TestSite")
        
        self.assertFalse(result)
        mock_apprise_obj_instance.add.assert_called_once_with("url1") # From init
        self.assertEqual(mock_apprise_obj_instance.notify.call_count, 3)
        mock_apprise_obj_instance.notify.assert_called_with(body="Test Body", title="Test Title")
        self.assertEqual(mock_ff_logging.log_failure.call_count, 3)

    @patch("builtins.open", new_callable=mock_open)
    @patch("tomllib.load")
    def test_send_notification_not_enabled(self, mock_tomllib_load, mock_file_open):
        mock_tomllib_load.return_value = {} # Not enabled (no Apprise URLs, no PB)
        
        # Patch apprise.Apprise as it's called in __init__
        with patch("apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = [] # No URLs successfully added
        with patch("notification_base.time.sleep", return_value=None):

                notifier = AppriseNotification("dummy_path.tomllib")
                self.assertFalse(notifier.enabled)
                result = notifier.send_notification("Test Title", "Test Body", "TestSite")
                self.assertFalse(result)
                mock_apprise_obj.notify.assert_not_called()


    @patch("builtins.open", new_callable=mock_open)
    @patch("tomllib.load")
    def test_get_service_name(self, mock_tomllib_load, mock_file_open):
        mock_tomllib_load.return_value = {}
        # Patch apprise.Apprise for __init__
        with patch("apprise_notification.apprise.Apprise"):
            notifier = AppriseNotification("dummy_path.tomllib")
        self.assertEqual(notifier.get_service_name(), "Apprise")


if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
