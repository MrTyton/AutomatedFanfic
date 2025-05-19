import unittest
from unittest.mock import patch, mock_open, MagicMock
import toml
from root.app.apprise_notification import AppriseNotification, JobConfigLoadError
from root.app.notification_wrapper import NotificationWrapper
# Assuming ff_logging is a module that can be mocked or is available.
# If not, we might need to mock it globally or handle its absence.

class TestAppriseNotification(unittest.TestCase):

    def _create_mock_toml_config(self, apprise_config=None, pushbullet_config=None):
        config_dict = {}
        if apprise_config is not None:
            config_dict["apprise"] = apprise_config
        if pushbullet_config is not None:
            config_dict["pushbullet"] = pushbullet_config
        return toml.dumps(config_dict)

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_initialization_reads_urls(self, mock_toml_load, mock_file_open):
        mock_config = {
            "apprise": {
                "urls": ["url1", "url2"]
            }
        }
        mock_toml_load.return_value = mock_config
        
        # Patch apprise.Apprise globally for this test to inspect its instance
        with patch("root.app.apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = ["url1", "url2"] # Simulate successful add

            notifier = AppriseNotification("dummy_path.toml")
            
            self.assertTrue(notifier.enabled)
            # Check that Apprise object was populated
            mock_apprise_obj.add.assert_any_call("url1")
            mock_apprise_obj.add.assert_any_call("url2")
            self.assertIn("url1", notifier.apprise_urls) # Original list still kept
            self.assertIn("url2", notifier.apprise_urls)

        mock_file_open.assert_called_once_with("dummy_path.toml", "r")

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_initialization_missing_apprise_section(self, mock_toml_load, mock_file_open):
        mock_toml_load.return_value = {} # No 'apprise' section
        with patch("root.app.apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = [] # No URLs added

            notifier = AppriseNotification("dummy_path.toml")
            self.assertEqual(notifier.apprise_urls, []) # Original list empty
            self.assertFalse(notifier.enabled) 
            mock_apprise_obj.add.assert_not_called()


    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_initialization_missing_urls_key(self, mock_toml_load, mock_file_open):
        mock_config = {"apprise": {}}
        mock_toml_load.return_value = mock_config
        with patch("root.app.apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = []

            notifier = AppriseNotification("dummy_path.toml")
            self.assertEqual(notifier.apprise_urls, [])
            self.assertFalse(notifier.enabled)
            mock_apprise_obj.add.assert_not_called()

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_initialization_empty_urls_list(self, mock_toml_load, mock_file_open):
        mock_config = {"apprise": {"urls": []}}
        mock_toml_load.return_value = mock_config
        with patch("root.app.apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = []
            
            notifier = AppriseNotification("dummy_path.toml")
            self.assertEqual(notifier.apprise_urls, [])
            self.assertFalse(notifier.enabled)
            mock_apprise_obj.add.assert_not_called()

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    @patch("root.app.apprise_notification.ff_logging")
    def test_initialization_processing_error_logs_and_disables(self, mock_ff_logging, mock_toml_load, mock_file_open):
        # Test that an error during the processing of apprise/pushbullet config
        # (after super().config is loaded) results in logging and notifier disabled.
        mock_config = {"apprise": {"urls": "not-a-list"}} # Invalid URL format
        mock_toml_load.return_value = mock_config

        with patch("root.app.apprise_notification.apprise.Apprise") as MockGlobalApprise:
            notifier = AppriseNotification("dummy_path.toml")
        
        mock_ff_logging.log_error.assert_called()
        self.assertFalse(notifier.enabled)

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_initialization_job_config_load_error_on_file_open(self, mock_toml_load, mock_file_open):
        # This test is for NotificationBase's __init__ failing
        mock_file_open.side_effect = FileNotFoundError("File not found")
        with self.assertRaises(JobConfigLoadError):
            AppriseNotification("dummy_path.toml")

    # --- Tests for auto-addition of Pushbullet URL ---
    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    @patch("root.app.apprise_notification.ff_logging")
    def test_init_auto_adds_pushbullet_url_no_device(self, mock_ff_logging, mock_toml_load, mock_file_open):
        mock_config = {
            "pushbullet": {"enabled": True, "api_key": "pb_api_key123"}
        }
        mock_toml_load.return_value = mock_config
        
        with patch("root.app.apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.add.return_value = True # Simulate successful add
            mock_apprise_obj.urls.return_value = ["pbul://pb_api_key123"]


            notifier = AppriseNotification("dummy_path.toml")

            self.assertTrue(notifier.enabled)
            expected_pb_url = "pbul://pb_api_key123"
            mock_apprise_obj.add.assert_called_once_with(expected_pb_url)
            self.assertIn(expected_pb_url, notifier.apprise_urls)
            mock_ff_logging.log_info.assert_any_call(f"Automatically added Pushbullet URL to Apprise: {expected_pb_url}")

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    @patch("root.app.apprise_notification.ff_logging")
    def test_init_auto_adds_pushbullet_url_with_device(self, mock_ff_logging, mock_toml_load, mock_file_open):
        mock_config = {
            "pushbullet": {"enabled": True, "api_key": "pb_api_key456", "device": "mydevice"}
        }
        mock_toml_load.return_value = mock_config

        with patch("root.app.apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.add.return_value = True
            mock_apprise_obj.urls.return_value = ["pbul://pb_api_key456/mydevice"]

            notifier = AppriseNotification("dummy_path.toml")
            self.assertTrue(notifier.enabled)
            expected_pb_url = "pbul://pb_api_key456/mydevice"
            mock_apprise_obj.add.assert_called_once_with(expected_pb_url)
            self.assertIn(expected_pb_url, notifier.apprise_urls)
            mock_ff_logging.log_info.assert_any_call(f"Automatically added Pushbullet URL to Apprise: {expected_pb_url}")

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_init_apprise_urls_and_auto_pushbullet(self, mock_toml_load, mock_file_open):
        mock_config = {
            "apprise": {"urls": ["http://customurl.com"]},
            "pushbullet": {"enabled": True, "api_key": "pb_key789", "device": "pb_device"}
        }
        mock_toml_load.return_value = mock_config
        
        with patch("root.app.apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.add.return_value = True
            # Simulate what urls() would return after adding both
            mock_apprise_obj.urls.return_value = ["http://customurl.com", "pbul://pb_key789/pb_device"]


            notifier = AppriseNotification("dummy_path.toml")
            self.assertTrue(notifier.enabled)
            mock_apprise_obj.add.assert_any_call("http://customurl.com")
            mock_apprise_obj.add.assert_any_call("pbul://pb_key789/pb_device")
            self.assertIn("http://customurl.com", notifier.apprise_urls)
            self.assertIn("pbul://pb_key789/pb_device", notifier.apprise_urls)

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_init_pushbullet_disabled(self, mock_toml_load, mock_file_open):
        mock_config = {
            "pushbullet": {"enabled": False, "api_key": "pb_api_key"}
        }
        mock_toml_load.return_value = mock_config
        with patch("root.app.apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = []

            notifier = AppriseNotification("dummy_path.toml")
            self.assertFalse(notifier.enabled)
            # Check that no pbul URL was added to apprise_urls list or apobj
            self.assertEqual(notifier.apprise_urls, [])
            mock_apprise_obj.add.assert_not_called()

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_init_pushbullet_no_api_key(self, mock_toml_load, mock_file_open):
        mock_config = {"pushbullet": {"enabled": True}} # No api_key
        mock_toml_load.return_value = mock_config
        with patch("root.app.apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = []

            notifier = AppriseNotification("dummy_path.toml")
            self.assertFalse(notifier.enabled)
            self.assertEqual(notifier.apprise_urls, [])
            mock_apprise_obj.add.assert_not_called()

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    @patch("root.app.apprise_notification.ff_logging")
    def test_init_duplicate_pushbullet_url(self, mock_ff_logging, mock_toml_load, mock_file_open):
        # Pushbullet URL is in apprise section AND also in pushbullet section
        pb_url = "pbul://pb_api_key/device"
        mock_config = {
            "apprise": {"urls": [pb_url]},
            "pushbullet": {"enabled": True, "api_key": "pb_api_key", "device": "device"}
        }
        mock_toml_load.return_value = mock_config
        with patch("root.app.apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.add.return_value = True
            mock_apprise_obj.urls.return_value = [pb_url] # Only one instance

            notifier = AppriseNotification("dummy_path.toml")
            self.assertTrue(notifier.enabled)
            # add should be called only once for the unique URL by the set logic before adding to apobj
            mock_apprise_obj.add.assert_called_once_with(pb_url)
            self.assertEqual(notifier.apprise_urls, [pb_url])
            mock_ff_logging.log_info.assert_any_call(f"Pushbullet URL {pb_url} was already present in Apprise config.")


    @patch("root.app.apprise_notification.apprise.Apprise") # Mock at class/method level for send_notification
    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    @patch("root.app.apprise_notification.ff_logging")
    def test_send_notification_success(self, mock_ff_logging, mock_toml_load, mock_file_open, MockAppriseClass):
        # This MockAppriseClass is for the one instantiated in AppriseNotification's __init__
        mock_apprise_obj_instance = MockAppriseClass.return_value # This is self.apobj
        mock_apprise_obj_instance.add.return_value = True # Simulate successful add during init
        mock_apprise_obj_instance.urls.return_value = ["url1", "url2"] # Simulate it has URLs after init
        mock_apprise_obj_instance.notify.return_value = True # Simulate successful notify

        mock_config = {"apprise": {"urls": ["url1", "url2"]}}
        mock_toml_load.return_value = mock_config
        
        notifier = AppriseNotification("dummy_path.toml") # apobj is created here
        self.assertTrue(notifier.enabled) # Ensure it's enabled for send to proceed

        result = notifier.send_notification("Test Title", "Test Body", "TestSite")
        
        self.assertTrue(result)
        # Add calls happen in init
        mock_apprise_obj_instance.add.assert_any_call("url1")
        mock_apprise_obj_instance.add.assert_any_call("url2")
        
        mock_apprise_obj_instance.notify.assert_called_once_with(body="Test Body", title="Test Title")
        mock_ff_logging.log_success.assert_called_once()


    @patch("root.app.apprise_notification.apprise.Apprise")
    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    @patch("root.app.apprise_notification.ff_logging")
    def test_send_notification_failure(self, mock_ff_logging, mock_toml_load, mock_file_open, MockAppriseClass):
        mock_apprise_obj_instance = MockAppriseClass.return_value
        mock_apprise_obj_instance.add.return_value = True
        mock_apprise_obj_instance.urls.return_value = ["url1"]
        mock_apprise_obj_instance.notify.return_value = False # Simulate Apprise failure

        mock_config = {"apprise": {"urls": ["url1"]}}
        mock_toml_load.return_value = mock_config
        
        notifier = AppriseNotification("dummy_path.toml")
        self.assertTrue(notifier.enabled)

        result = notifier.send_notification("Test Title", "Test Body", "TestSite")
        
        self.assertFalse(result)
        mock_apprise_obj_instance.add.assert_called_once_with("url1") # From init
        mock_apprise_obj_instance.notify.assert_called_once_with(body="Test Body", title="Test Title")
        mock_ff_logging.log_failure.assert_called_once()

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_send_notification_not_enabled(self, mock_toml_load, mock_file_open):
        mock_toml_load.return_value = {} # Not enabled (no Apprise URLs, no PB)
        
        # Patch apprise.Apprise as it's called in __init__
        with patch("root.app.apprise_notification.apprise.Apprise") as MockGlobalApprise:
            mock_apprise_obj = MockGlobalApprise.return_value
            mock_apprise_obj.urls.return_value = [] # No URLs successfully added

            notifier = AppriseNotification("dummy_path.toml")
            self.assertFalse(notifier.enabled)
            result = notifier.send_notification("Test Title", "Test Body", "TestSite")
            self.assertFalse(result)
            mock_apprise_obj.notify.assert_not_called()


    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_get_service_name(self, mock_toml_load, mock_file_open):
        mock_toml_load.return_value = {}
        # Patch apprise.Apprise for __init__
        with patch("root.app.apprise_notification.apprise.Apprise"):
            notifier = AppriseNotification("dummy_path.toml")
        self.assertEqual(notifier.get_service_name(), "Apprise")


class TestNotificationWrapperWithApprise(unittest.TestCase):

    def _create_mock_toml_content(self, apprise_settings=None, pushbullet_settings=None):
        config = {}
        if apprise_settings:
            config["apprise"] = apprise_settings
        if pushbullet_settings:
            config["pushbullet"] = pushbullet_settings
        return toml.dumps(config)

    @patch("builtins.open", new_callable=mock_open)
    @patch("root.app.notification_wrapper.AppriseNotification") # Patch the class used by NotificationWrapper
    def test_wrapper_with_only_apprise_urls(self, MockAppriseNotification, mock_file_open):
        # Scenario: Apprise URLs configured, Pushbullet not configured or disabled
        toml_content = self._create_mock_toml_content(
            apprise_settings={"urls": ["http://apprise.url"]},
            pushbullet_settings={"enabled": False}
        )
        mock_file_open.return_value.read.return_value = toml_content

        mock_apprise_worker_instance = MockAppriseNotification.return_value
        mock_apprise_worker_instance.is_enabled.return_value = True # Apprise worker is enabled

        wrapper = NotificationWrapper(toml_path="dummy.toml")
        
        MockAppriseNotification.assert_called_once_with(toml_path="dummy.toml")
        self.assertEqual(len(wrapper.notification_workers), 1)
        self.assertIs(wrapper.notification_workers[0], mock_apprise_worker_instance)

    @patch("builtins.open", new_callable=mock_open)
    @patch("root.app.notification_wrapper.AppriseNotification")
    def test_wrapper_with_only_pushbullet_config(self, MockAppriseNotification, mock_file_open):
        # Scenario: No Apprise URLs, only Pushbullet configured and enabled
        # AppriseNotification should internally handle this and become enabled.
        toml_content = self._create_mock_toml_content(
            apprise_settings={"urls": []}, # No direct Apprise URLs
            pushbullet_settings={"enabled": True, "api_key": "pbkey123"}
        )
        mock_file_open.return_value.read.return_value = toml_content

        mock_apprise_worker_instance = MockAppriseNotification.return_value
        # AppriseNotification's own is_enabled() will determine this based on the auto-added pb URL
        mock_apprise_worker_instance.is_enabled.return_value = True 

        wrapper = NotificationWrapper(toml_path="dummy.toml")
        
        MockAppriseNotification.assert_called_once_with(toml_path="dummy.toml")
        self.assertEqual(len(wrapper.notification_workers), 1)
        self.assertIs(wrapper.notification_workers[0], mock_apprise_worker_instance)
        # We could add more assertions here by having AppriseNotification expose its internal Apprise obj
        # or the URLs it configured, if we wanted to verify the pbul:// URL was indeed set.
        # For now, we trust AppriseNotification's is_enabled and its own tests.

    @patch("builtins.open", new_callable=mock_open)
    @patch("root.app.notification_wrapper.AppriseNotification")
    def test_wrapper_with_apprise_and_pushbullet_config(self, MockAppriseNotification, mock_file_open):
        # Scenario: Both Apprise URLs and Pushbullet config are present.
        # AppriseNotification should merge them (internally, PB URL added to its set of URLs).
        toml_content = self._create_mock_toml_content(
            apprise_settings={"urls": ["http://apprise.url"]},
            pushbullet_settings={"enabled": True, "api_key": "pbkey456"}
        )
        mock_file_open.return_value.read.return_value = toml_content

        mock_apprise_worker_instance = MockAppriseNotification.return_value
        mock_apprise_worker_instance.is_enabled.return_value = True

        wrapper = NotificationWrapper(toml_path="dummy.toml")
        
        MockAppriseNotification.assert_called_once_with(toml_path="dummy.toml")
        self.assertEqual(len(wrapper.notification_workers), 1)
        self.assertIs(wrapper.notification_workers[0], mock_apprise_worker_instance)

    @patch("builtins.open", new_callable=mock_open)
    @patch("root.app.notification_wrapper.AppriseNotification")
    def test_wrapper_apprise_not_enabled(self, MockAppriseNotification, mock_file_open):
        # Scenario: Neither Apprise URLs nor enabled Pushbullet config. AppriseNotification should not be enabled.
        toml_content = self._create_mock_toml_content(
            apprise_settings={"urls": []},
            pushbullet_settings={"enabled": False, "api_key": "pbkey789"}
        )
        mock_file_open.return_value.read.return_value = toml_content

        mock_apprise_worker_instance = MockAppriseNotification.return_value
        mock_apprise_worker_instance.is_enabled.return_value = False # Apprise worker is NOT enabled

        wrapper = NotificationWrapper(toml_path="dummy.toml")
        
        MockAppriseNotification.assert_called_once_with(toml_path="dummy.toml")
        self.assertEqual(len(wrapper.notification_workers), 0)

    @patch("builtins.open", new_callable=mock_open)
    @patch('root.app.notification_wrapper.AppriseNotification')
    @patch('root.app.notification_wrapper.ff_logging') 
    def test_notification_wrapper_initialization_logs(self, mock_ff_logging, MockAppriseNotification, mock_file_open):
        toml_content = self._create_mock_toml_content(
            apprise_settings={"urls": ["http://apprise.url"]},
            pushbullet_settings={"enabled": True, "api_key": "pbkey"} # Will be auto-added by AppriseNotification
        )
        mock_file_open.return_value.read.return_value = toml_content

        mock_apprise_instance = MockAppriseNotification.return_value
        mock_apprise_instance.is_enabled.return_value = True # AppriseNotification is enabled

        wrapper = NotificationWrapper(toml_path="dummy.toml")

        self.assertEqual(len(wrapper.notification_workers), 1)
        self.assertIs(wrapper.notification_workers[0], mock_apprise_instance)
        
        mock_ff_logging.log_info.assert_any_call("AppriseNotification worker added and enabled.")
        # Verify no logs about PushbulletNotification being added/not added, as it's handled internally by AppriseNotification
        for call_args in mock_ff_logging.log_info.call_args_list:
            self.assertNotIn("PushbulletNotification", call_args[0][0])


    @patch("builtins.open", new_callable=mock_open)
    @patch('root.app.notification_wrapper.AppriseNotification')
    @patch('root.app.notification_wrapper.ff_logging')
    def test_notification_wrapper_apprise_init_fails(self, mock_ff_logging, MockAppriseNotification, mock_file_open):
        # Scenario: AppriseNotification itself throws an exception during its __init__
        toml_content = self._create_mock_toml_content() # Some valid TOML
        mock_file_open.return_value.read.return_value = toml_content

        MockAppriseNotification.side_effect = Exception("Apprise Init Failed")

        wrapper = NotificationWrapper(toml_path="dummy.toml")

        self.assertEqual(len(wrapper.notification_workers), 0) # No workers added
        mock_ff_logging.log_error.assert_any_call("Failed to initialize AppriseNotification: Apprise Init Failed")


if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
