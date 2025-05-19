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
        
        notifier = AppriseNotification("dummy_path.toml")
        self.assertEqual(notifier.apprise_urls, ["url1", "url2"])
        self.assertTrue(notifier.enabled)
        mock_file_open.assert_called_once_with("dummy_path.toml", "r")

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_initialization_missing_apprise_section(self, mock_toml_load, mock_file_open):
        mock_toml_load.return_value = {} # No 'apprise' section
        
        notifier = AppriseNotification("dummy_path.toml")
        self.assertEqual(notifier.apprise_urls, [])
        self.assertFalse(notifier.enabled) # Should be false if no URLs and no PB fallback

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_initialization_missing_urls_key(self, mock_toml_load, mock_file_open):
        mock_config = {
            "apprise": {} # 'apprise' section exists, but no 'urls' key
        }
        mock_toml_load.return_value = mock_config
        
        notifier = AppriseNotification("dummy_path.toml")
        self.assertEqual(notifier.apprise_urls, [])
        self.assertFalse(notifier.enabled)

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_initialization_empty_urls_list(self, mock_toml_load, mock_file_open):
        mock_config = {
            "apprise": {
                "urls": []
            }
        }
        mock_toml_load.return_value = mock_config
        
        notifier = AppriseNotification("dummy_path.toml")
        self.assertEqual(notifier.apprise_urls, [])
        self.assertFalse(notifier.enabled)

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    @patch("root.app.apprise_notification.ff_logging") # Mocking ff_logging
    def test_initialization_error_reading_config(self, mock_ff_logging, mock_toml_load, mock_file_open):
        mock_toml_load.side_effect = Exception("TOML parse error")
        
        with self.assertRaises(JobConfigLoadError):
            AppriseNotification("dummy_path.toml")
        mock_ff_logging.log_error.assert_called_once()

    @patch("root.app.apprise_notification.apprise.Apprise")
    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    @patch("root.app.apprise_notification.ff_logging")
    def test_send_notification_success(self, mock_ff_logging, mock_toml_load, mock_file_open, MockApprise):
        mock_config = {"apprise": {"urls": ["url1", "url2"]}}
        mock_toml_load.return_value = mock_config
        
        mock_apprise_instance = MockApprise.return_value
        mock_apprise_instance.notify.return_value = True
        
        notifier = AppriseNotification("dummy_path.toml")
        result = notifier.send_notification("Test Title", "Test Body", "TestSite")
        
        self.assertTrue(result)
        mock_apprise_instance.add.assert_any_call("url1")
        mock_apprise_instance.add.assert_any_call("url2")
        self.assertEqual(mock_apprise_instance.add.call_count, 2)
        mock_apprise_instance.notify.assert_called_once_with(body="Test Body", title="Test Title")
        mock_ff_logging.log_success.assert_called_once()

    @patch("root.app.apprise_notification.apprise.Apprise")
    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    @patch("root.app.apprise_notification.ff_logging")
    def test_send_notification_failure(self, mock_ff_logging, mock_toml_load, mock_file_open, MockApprise):
        mock_config = {"apprise": {"urls": ["url1"]}}
        mock_toml_load.return_value = mock_config
        
        mock_apprise_instance = MockApprise.return_value
        mock_apprise_instance.notify.return_value = False # Simulate Apprise failure
        
        notifier = AppriseNotification("dummy_path.toml")
        result = notifier.send_notification("Test Title", "Test Body", "TestSite")
        
        self.assertFalse(result)
        mock_apprise_instance.add.assert_called_once_with("url1")
        mock_apprise_instance.notify.assert_called_once_with(body="Test Body", title="Test Title")
        mock_ff_logging.log_failure.assert_called_once()

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_send_notification_not_enabled(self, mock_toml_load, mock_file_open):
        mock_toml_load.return_value = {} # Not enabled
        
        notifier = AppriseNotification("dummy_path.toml")
        result = notifier.send_notification("Test Title", "Test Body", "TestSite")
        self.assertFalse(result)

    # --- Tests for can_handle_pushbullet ---
    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_can_handle_pushbullet_true_exact_match(self, mock_toml_load, mock_file_open):
        mock_config = {
            "apprise": {"urls": ["pbul://testapikey/testdevice"]},
            "pushbullet": {"enabled": True, "api_key": "testapikey", "device_iden": "testdevice"}
        }
        mock_toml_load.return_value = mock_config
        notifier = AppriseNotification("dummy_path.toml")
        self.assertTrue(notifier.can_handle_pushbullet())

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_can_handle_pushbullet_true_broadcast_url(self, mock_toml_load, mock_file_open):
        mock_config = {
            "apprise": {"urls": ["pbul://testapikey/*"]},
            "pushbullet": {"enabled": True, "api_key": "testapikey", "device_iden": "testdevice"}
        }
        mock_toml_load.return_value = mock_config
        notifier = AppriseNotification("dummy_path.toml")
        self.assertTrue(notifier.can_handle_pushbullet())
        
    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_can_handle_pushbullet_true_apikey_only_in_apprise(self, mock_toml_load, mock_file_open):
        # Apprise has pbul://apikey which implies broadcast, Pushbullet config has device
        mock_config = {
            "apprise": {"urls": ["pbul://testapikey"]},
            "pushbullet": {"enabled": True, "api_key": "testapikey", "device_iden": "testdevice"}
        }
        mock_toml_load.return_value = mock_config
        notifier = AppriseNotification("dummy_path.toml")
        self.assertTrue(notifier.can_handle_pushbullet())

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_can_handle_pushbullet_false_no_pb_config(self, mock_toml_load, mock_file_open):
        mock_config = {"apprise": {"urls": ["someotherurl"]}} # No pushbullet section
        mock_toml_load.return_value = mock_config
        notifier = AppriseNotification("dummy_path.toml")
        self.assertFalse(notifier.can_handle_pushbullet())

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_can_handle_pushbullet_false_pb_disabled(self, mock_toml_load, mock_file_open):
        mock_config = {
            "apprise": {"urls": ["pbul://testapikey"]},
            "pushbullet": {"enabled": False, "api_key": "testapikey"}
        }
        mock_toml_load.return_value = mock_config
        notifier = AppriseNotification("dummy_path.toml")
        self.assertFalse(notifier.can_handle_pushbullet())

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_can_handle_pushbullet_false_no_matching_url(self, mock_toml_load, mock_file_open):
        mock_config = {
            "apprise": {"urls": ["otherprotocol://someconfig"]},
            "pushbullet": {"enabled": True, "api_key": "testapikey"}
        }
        mock_toml_load.return_value = mock_config
        notifier = AppriseNotification("dummy_path.toml")
        self.assertFalse(notifier.can_handle_pushbullet())

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_can_handle_pushbullet_false_no_apprise_urls(self, mock_toml_load, mock_file_open):
        mock_config = {
            "apprise": {"urls": []}, # No apprise urls
            "pushbullet": {"enabled": True, "api_key": "testapikey"}
        }
        mock_toml_load.return_value = mock_config
        notifier = AppriseNotification("dummy_path.toml")
        self.assertFalse(notifier.can_handle_pushbullet())

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    @patch("root.app.apprise_notification.ff_logging")
    def test_can_handle_pushbullet_exception_in_config_access(self, mock_ff_logging, mock_toml_load, mock_file_open):
        # Simulate self.config.get("pushbullet") raising an error
        mock_toml_load.return_value = {"apprise": {"urls": ["pbul://testapikey"]}}
        notifier = AppriseNotification("dummy_path.toml")
        
        # Make self.config a MagicMock that raises an exception when 'pushbullet' is accessed
        notifier.config = MagicMock()
        notifier.config.get.side_effect = Exception("Simulated config access error")
        
        self.assertFalse(notifier.can_handle_pushbullet())
        mock_ff_logging.log_error.assert_called_once()

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_get_service_name(self, mock_toml_load, mock_file_open):
        mock_toml_load.return_value = {}
        notifier = AppriseNotification("dummy_path.toml")
        self.assertEqual(notifier.get_service_name(), "Apprise")

    @patch("builtins.open", new_callable=mock_open)
    @patch("toml.load")
    def test_enabled_true_if_can_handle_pushbullet(self, mock_toml_load, mock_file_open):
        # Test that self.enabled is true if apprise_urls is empty but can_handle_pushbullet is true
        mock_config = {
            # No apprise urls
            "pushbullet": {"enabled": True, "api_key": "testapikey"}
        }
        mock_toml_load.return_value = mock_config
        
        # We need to make can_handle_pushbullet return True for this specific test
        # This requires a bit more direct patching or setup
        with patch.object(AppriseNotification, 'can_handle_pushbullet', return_value=True) as mock_can_handle_pb:
            notifier = AppriseNotification("dummy_path.toml")
            # Ensure can_handle_pushbullet was actually called during init
            mock_can_handle_pb.assert_called_once() 
            self.assertTrue(notifier.enabled)


class TestNotificationWrapperWithApprise(unittest.TestCase):

    def _create_mock_toml_content(self, apprise_settings=None, pushbullet_settings=None):
        config = {}
        if apprise_settings:
            config["apprise"] = apprise_settings
        if pushbullet_settings:
            config["pushbullet"] = pushbullet_settings
        return toml.dumps(config)

    @patch("builtins.open", new_callable=mock_open)
    def test_apprise_enabled_pb_enabled_apprise_handles_pb(self, mock_file):
        # Scenario 1: Apprise enabled, Pushbullet enabled, Apprise *can* handle Pushbullet.
        # Expected: Only Apprise worker added (or specifically, Pushbullet worker *not* added).
        toml_content = self._create_mock_toml_content(
            apprise_settings={"urls": ["pbul://pbkey"]},
            pushbullet_settings={"enabled": True, "api_key": "pbkey"}
        )
        mock_file.return_value.read.return_value = toml_content

        wrapper = NotificationWrapper(toml_path="dummy.toml")
        
        self.assertEqual(len(wrapper.notification_workers), 1)
        self.assertIsInstance(wrapper.notification_workers[0], AppriseNotification)
        # Verify AppriseNotification's can_handle_pushbullet was True
        self.assertTrue(wrapper.notification_workers[0].can_handle_pushbullet())


    @patch("builtins.open", new_callable=mock_open)
    def test_apprise_enabled_pb_enabled_apprise_cannot_handle_pb(self, mock_file):
        # Scenario 2: Apprise enabled, Pushbullet enabled, Apprise *cannot* handle Pushbullet.
        # Expected: Both workers added.
        toml_content = self._create_mock_toml_content(
            apprise_settings={"urls": ["other://service"]}, # Apprise enabled, but no pbul URL
            pushbullet_settings={"enabled": True, "api_key": "pbkey"} # Pushbullet enabled
        )
        mock_file.return_value.read.return_value = toml_content
        
        wrapper = NotificationWrapper(toml_path="dummy.toml")
        
        self.assertEqual(len(wrapper.notification_workers), 2)
        worker_types = sorted([type(w).__name__ for w in wrapper.notification_workers])
        self.assertIn("AppriseNotification", worker_types)
        self.assertIn("PushbulletNotification", worker_types)
        
        # Find the apprise worker and check its can_handle_pushbullet
        apprise_worker = next(w for w in wrapper.notification_workers if isinstance(w, AppriseNotification))
        self.assertFalse(apprise_worker.can_handle_pushbullet())


    @patch("builtins.open", new_callable=mock_open)
    def test_apprise_disabled_pb_enabled(self, mock_file):
        # Scenario 3: Apprise disabled (no URLs), Pushbullet enabled.
        # Expected: Only Pushbullet worker added.
        toml_content = self._create_mock_toml_content(
            apprise_settings={"urls": []}, # Apprise configured but no URLs
            pushbullet_settings={"enabled": True, "api_key": "pbkey"}
        )
        mock_file.return_value.read.return_value = toml_content
        
        wrapper = NotificationWrapper(toml_path="dummy.toml")
        
        self.assertEqual(len(wrapper.notification_workers), 1)
        self.assertIsInstance(wrapper.notification_workers[0], MagicMock) # PushbulletNotification
        # We expect PushbulletNotification, but because AppriseNotification is imported in notification_wrapper
        # and PushbulletNotification is also imported there, the mock setup might be tricky.
        # For now, let's check the type name based on how NotificationWrapper initializes them.
        # This test will likely need refinement based on actual PushbulletNotification mock.
        # For now, let's assume it's a MagicMock if Apprise is not the one.
        # A better way would be to patch AppriseNotification and PushbulletNotification directly.
        
        # To make this test more robust, we should patch the constructors
        with patch('root.app.notification_wrapper.AppriseNotification') as MockApprise, \
             patch('root.app.notification_wrapper.PushbulletNotification') as MockPushbullet:
            
            mock_apprise_instance = MockApprise.return_value
            mock_apprise_instance.is_enabled.return_value = False # Apprise is not enabled
            
            mock_pb_instance = MockPushbullet.return_value
            mock_pb_instance.is_enabled.return_value = True # Pushbullet is enabled
            
            # Toml load needs to be consistent with this
            mock_file.return_value.read.return_value = self._create_mock_toml_content(
                apprise_settings={"urls": []}, 
                pushbullet_settings={"enabled": True, "api_key": "pbkey"}
            )

            wrapper = NotificationWrapper(toml_path="dummy.toml")
            
            MockApprise.assert_called_once_with("dummy.toml")
            MockPushbullet.assert_called_once_with("dummy.toml")
            
            self.assertEqual(len(wrapper.notification_workers), 1)
            self.assertIs(wrapper.notification_workers[0], mock_pb_instance)


    @patch("builtins.open", new_callable=mock_open)
    def test_apprise_enabled_pb_disabled(self, mock_file):
        # Scenario 4: Apprise enabled (but no Pushbullet-equivalent URL), Pushbullet disabled.
        # Expected: Only Apprise worker added.
        toml_content = self._create_mock_toml_content(
            apprise_settings={"urls": ["other://service"]},
            pushbullet_settings={"enabled": False, "api_key": "pbkey"} # Pushbullet disabled
        )
        mock_file.return_value.read.return_value = toml_content

        with patch('root.app.notification_wrapper.AppriseNotification') as MockApprise, \
             patch('root.app.notification_wrapper.PushbulletNotification') as MockPushbullet:

            mock_apprise_instance = MockApprise.return_value
            mock_apprise_instance.is_enabled.return_value = True
            mock_apprise_instance.can_handle_pushbullet.return_value = False # Apprise cannot handle (no pbul url)

            mock_pb_instance = MockPushbullet.return_value
            mock_pb_instance.is_enabled.return_value = False # Pushbullet is not enabled

            wrapper = NotificationWrapper(toml_path="dummy.toml")

            MockApprise.assert_called_once_with("dummy.toml")
            MockPushbullet.assert_called_once_with("dummy.toml")

            self.assertEqual(len(wrapper.notification_workers), 1)
            self.assertIs(wrapper.notification_workers[0], mock_apprise_instance)


    @patch("builtins.open", new_callable=mock_open)
    @patch('root.app.notification_wrapper.AppriseNotification')
    @patch('root.app.notification_wrapper.PushbulletNotification')
    @patch('root.app.notification_wrapper.ff_logging') # Mock ff_logging in NotificationWrapper
    def test_notification_wrapper_initialization_logs(self, mock_ff_logging, MockPushbullet, MockApprise, mock_file):
        toml_content = self._create_mock_toml_content(
            apprise_settings={"urls": ["pbul://pbkey"]},
            pushbullet_settings={"enabled": True, "api_key": "pbkey"}
        )
        mock_file.return_value.read.return_value = toml_content

        mock_apprise_instance = MockApprise.return_value
        mock_apprise_instance.is_enabled.return_value = True
        mock_apprise_instance.can_handle_pushbullet.return_value = True # Apprise handles PB

        mock_pb_instance = MockPushbullet.return_value
        mock_pb_instance.is_enabled.return_value = True # Pushbullet is technically enabled in config
        # Mock the config attribute for Pushbullet to simulate it being enabled in TOML
        mock_pb_instance.config = {"pushbullet": {"enabled": True, "api_key": "pbkey"}}


        wrapper = NotificationWrapper(toml_path="dummy.toml")

        self.assertEqual(len(wrapper.notification_workers), 1)
        self.assertIs(wrapper.notification_workers[0], mock_apprise_instance)
        
        # Check logs
        mock_ff_logging.log_info.assert_any_call("AppriseNotification worker added.")
        # This log happens because PB is enabled, but Apprise handles it
        mock_ff_logging.log_info.assert_any_call("PushbulletNotification not added as Apprise can handle Pushbullet.")


    @patch("builtins.open", new_callable=mock_open)
    @patch('root.app.notification_wrapper.AppriseNotification')
    @patch('root.app.notification_wrapper.PushbulletNotification')
    @patch('root.app.notification_wrapper.ff_logging')
    def test_notification_wrapper_apprise_init_fails(self, mock_ff_logging, MockPushbullet, MockApprise, mock_file):
        toml_content = self._create_mock_toml_content(
            pushbullet_settings={"enabled": True, "api_key": "pbkey"}
        )
        mock_file.return_value.read.return_value = toml_content

        MockApprise.side_effect = Exception("Apprise Init Failed") # Apprise fails to initialize

        mock_pb_instance = MockPushbullet.return_value
        mock_pb_instance.is_enabled.return_value = True
        mock_pb_instance.config = {"pushbullet": {"enabled": True, "api_key": "pbkey"}}


        wrapper = NotificationWrapper(toml_path="dummy.toml")

        self.assertEqual(len(wrapper.notification_workers), 1) # Only Pushbullet should be there
        self.assertIs(wrapper.notification_workers[0], mock_pb_instance)
        
        mock_ff_logging.log_error.assert_any_call("Failed to initialize AppriseNotification: Apprise Init Failed")
        mock_ff_logging.log_info.assert_any_call("PushbulletNotification worker added as Apprise cannot handle Pushbullet.")


if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
