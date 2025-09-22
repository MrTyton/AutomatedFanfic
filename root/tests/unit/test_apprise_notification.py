import unittest
from unittest.mock import patch, mock_open, MagicMock

from apprise_notification import AppriseNotification
from notification_wrapper import NotificationWrapper
from parameterized import parameterized
import notification_base
import apprise_notification
import io
from config_models import (
    AppConfig,
    AppriseConfig,
    PushbulletConfig,
    EmailConfig,
    CalibreConfig,
)


class TestAppriseNotification(unittest.TestCase):

    @parameterized.expand(
        [
            ("single_url", ["url1"], ["url1"]),
            ("multiple_urls", ["url1", "url2"], ["url1", "url2"]),
            (
                "many_urls",
                ["url1", "url2", "url3", "url4"],
                ["url1", "url2", "url3", "url4"],
            ),
        ]
    )
    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_initialization_reads_urls(
        self, name, input_urls, expected_urls, mock_load_config, MockGlobalApprise
    ):
        # Setup mock configuration
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=input_urls),
            pushbullet=PushbulletConfig(),  # Default disabled
        )
        mock_load_config.return_value = mock_config

        # Setup mock apprise
        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True
        mock_apprise_obj.urls.return_value = expected_urls

        notifier = AppriseNotification("dummy_path.toml")

        self.assertTrue(notifier.enabled)
        # Check that Apprise object was populated
        for url in expected_urls:
            mock_apprise_obj.add.assert_any_call(url)
            self.assertIn(url, notifier.apprise_urls)
        mock_load_config.assert_called_once_with("dummy_path.toml")

    @parameterized.expand(
        [
            ("empty_apprise", AppriseConfig(), PushbulletConfig()),
            ("empty_urls", AppriseConfig(urls=[]), PushbulletConfig()),
        ]
    )
    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_initialization_missing_apprise_section(
        self,
        name,
        apprise_config,
        pushbullet_config,
        mock_load_config,
        MockGlobalApprise,
    ):
        # Setup mock config with empty apprise
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=apprise_config,
            pushbullet=pushbullet_config,
        )
        mock_load_config.return_value = mock_config

        # Setup mock apprise
        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.urls.return_value = []

        notifier = AppriseNotification("dummy_path.toml")

        self.assertEqual(notifier.apprise_urls, set())
        self.assertFalse(notifier.enabled)
        mock_apprise_obj.add.assert_not_called()

    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_initialization_missing_urls_key(self, mock_load_config, MockGlobalApprise):
        # Setup mock config with empty apprise
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),  # Default empty
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.urls.return_value = []

        notifier = AppriseNotification("dummy_path.toml")
        self.assertEqual(notifier.apprise_urls, set())
        self.assertFalse(notifier.enabled)
        mock_apprise_obj.add.assert_not_called()

    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_initialization_empty_urls_list(self, mock_load_config, MockGlobalApprise):
        # Setup mock config with empty URLs
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=[]),  # Empty list
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.urls.return_value = []

        notifier = AppriseNotification("dummy_path.toml")
        self.assertEqual(notifier.apprise_urls, set())
        self.assertFalse(notifier.enabled)
        mock_apprise_obj.add.assert_not_called()

    # --- Tests for auto-addition of Pushbullet URL ---
    @parameterized.expand(
        [
            ("no_device", True, "pb_api_key123", "", "pbul://pb_api_key123"),
            ("with_device", True, "pb_api_key456", "my_device", "pbul://pb_api_key456"),
            ("different_token", True, "different_token", "", "pbul://different_token"),
        ]
    )
    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    @patch("apprise_notification.ff_logging")
    def test_init_auto_adds_pushbullet_url(
        self,
        name,
        enabled,
        token,
        device,
        expected_pb_url,
        mock_ff_logging,
        mock_load_config,
        MockGlobalApprise,
    ):
        # Setup mock config with enabled pushbullet
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(enabled=enabled, api_key=token, device=device),
        )
        mock_load_config.return_value = mock_config

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True  # Simulate successful add
        mock_apprise_obj.urls.return_value = [expected_pb_url]

        notifier = AppriseNotification("dummy_path.toml")

        self.assertTrue(notifier.enabled)
        mock_apprise_obj.add.assert_called_once_with(expected_pb_url)
        self.assertIn(expected_pb_url, notifier.apprise_urls)
        mock_ff_logging.log_debug.assert_any_call(
            f"Automatically added Pushbullet URL to Apprise: {expected_pb_url}"
        )

    @parameterized.expand(
        [
            ("disabled", False, "pb_api_key", ""),
            ("disabled_with_device", False, "pb_api_key", "device"),
            ("empty_token", False, "", ""),
        ]
    )
    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_init_pushbullet_disabled_scenarios(
        self, name, enabled, token, device, mock_load_config, MockGlobalApprise
    ):
        # Setup mock config with disabled/invalid pushbullet
        pushbullet_config = PushbulletConfig(enabled=enabled)
        if token:  # Only set token if not empty (for validation)
            pushbullet_config = PushbulletConfig(
                enabled=enabled, api_key=token, device=device
            )

        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),
            pushbullet=pushbullet_config,
        )
        mock_load_config.return_value = mock_config

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.urls.return_value = []

        notifier = AppriseNotification("dummy_path.toml")
        self.assertFalse(notifier.enabled)
        # Check that no pbul URL was added to apprise_urls list or apobj
        self.assertEqual(notifier.apprise_urls, set())
        mock_apprise_obj.add.assert_not_called()

    @parameterized.expand(
        [
            (
                "notification_success",
                None,
                "Test Title",
                "Test Body",
                "TestSite",
            ),  # retry_decorator returns None on success
            ("different_title", None, "Another Title", "Another Body", "AnotherSite"),
            ("empty_body", None, "Title Only", "", "EmptySite"),
        ]
    )
    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    @patch("apprise_notification.ff_logging")
    def test_send_notification_success(
        self,
        name,
        expected_result,
        title,
        body,
        site,
        mock_ff_logging,
        mock_load_config,
        MockAppriseClass,
    ):
        # Setup mock config
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=["url1"]),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config

        mock_apprise_obj_instance = MockAppriseClass.return_value
        mock_apprise_obj_instance.add.return_value = True
        mock_apprise_obj_instance.urls.return_value = ["url1"]
        mock_apprise_obj_instance.notify.return_value = True  # Simulate success

        notifier = AppriseNotification("dummy_path.toml")
        self.assertTrue(notifier.enabled)

        result = notifier.send_notification(title, body, site)

        self.assertIsNone(result)  # retry_decorator returns None on success
        mock_apprise_obj_instance.add.assert_called_once_with("url1")  # From init
        mock_apprise_obj_instance.notify.assert_called_once_with(body=body, title=title)

    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    @patch("apprise_notification.ff_logging")
    def test_send_notification_failure(
        self, mock_ff_logging, mock_load_config, MockAppriseClass
    ):
        # Setup mock config
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=["url1"]),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config

        mock_apprise_obj_instance = MockAppriseClass.return_value
        mock_apprise_obj_instance.add.return_value = True
        mock_apprise_obj_instance.urls.return_value = ["url1"]
        mock_apprise_obj_instance.notify.return_value = (
            False  # Simulate Apprise failure
        )

        notifier = AppriseNotification("dummy_path.toml")
        self.assertTrue(notifier.enabled)

        with patch("notification_base.time.sleep", return_value=None):
            result = notifier.send_notification("Test Title", "Test Body", "TestSite")

        self.assertFalse(result)
        mock_apprise_obj_instance.add.assert_called_once_with("url1")  # From init
        self.assertEqual(mock_apprise_obj_instance.notify.call_count, 3)
        mock_apprise_obj_instance.notify.assert_called_with(
            body="Test Body", title="Test Title"
        )
        self.assertEqual(mock_ff_logging.log_failure.call_count, 3)

    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_send_notification_not_enabled(self, mock_load_config, MockGlobalApprise):
        # Setup mock config with no apprise or pushbullet
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),  # Empty
            pushbullet=PushbulletConfig(),  # Disabled
        )
        mock_load_config.return_value = mock_config

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.urls.return_value = []  # No URLs successfully added

        with patch("notification_base.time.sleep", return_value=None):
            notifier = AppriseNotification("dummy_path.toml")
            self.assertFalse(notifier.enabled)
            result = notifier.send_notification("Test Title", "Test Body", "TestSite")
            self.assertFalse(result)
            mock_apprise_obj.notify.assert_not_called()

    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_get_service_name(self, mock_load_config, MockGlobalApprise):
        # Setup minimal mock config
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config

        notifier = AppriseNotification("dummy_path.toml")
        self.assertEqual(notifier.get_service_name(), "Apprise")


class TestAppriseNotificationFailures(unittest.TestCase):
    """Test failure scenarios and error handling in AppriseNotification."""

    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_config_none_initialization(self, mock_load_config, MockGlobalApprise):
        """Test initialization when config loading returns None."""
        # ConfigManager returns None (line 90)
        mock_load_config.return_value = None

        notifier = AppriseNotification("dummy_path.toml")

        # Should be disabled when config is None
        self.assertFalse(notifier.enabled)
        self.assertIsNone(notifier.config)

        # AppRise object should not be configured
        MockGlobalApprise.assert_called_once()
        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.assert_not_called()

    @patch("apprise_notification.ff_logging.log_debug")
    @patch("apprise_notification.requests.get")
    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_pushbullet_device_not_found(
        self, mock_load_config, MockGlobalApprise, mock_requests_get, mock_log_debug
    ):
        """Test Pushbullet device not found scenario (lines 128-130)."""
        # Setup config with Pushbullet enabled and device specified
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=[]),
            pushbullet=PushbulletConfig(
                enabled=True, api_key="test_api_key", device="nonexistent_device"
            ),
        )
        mock_load_config.return_value = mock_config

        # Mock requests.get to return devices without the target device
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "devices": [
                {
                    "iden": "device1",
                    "active": True,
                    "pushable": True,
                    "nickname": "other_device",
                }
            ]
        }
        mock_requests_get.return_value = mock_response

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True
        mock_apprise_obj.urls.return_value = ["pbal://test_api_key"]

        notifier = AppriseNotification("dummy_path.toml")

        # Verify API call was made with correct headers
        mock_requests_get.assert_called_once_with(
            "https://api.pushbullet.com/v2/devices",
            headers={"Access-Token": "test_api_key"},
        )

        # Should continue with basic URL since device not found
        self.assertTrue(notifier.enabled)

    @patch("apprise_notification.ff_logging.log_failure")
    @patch("apprise_notification.requests.get")
    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_apprise_configuration_exception(
        self, mock_load_config, MockGlobalApprise, mock_requests_get, mock_log_failure
    ):
        """Test exception during Apprise configuration processing (lines 148-150)."""
        # Setup config that will cause an exception during Pushbullet processing
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=["valid://url"]),
            pushbullet=PushbulletConfig(
                enabled=True,
                api_key="test_api_key",
                device="my_device",  # This will trigger device lookup
            ),
        )
        mock_load_config.return_value = mock_config

        # Make requests.get raise an exception during device lookup
        mock_requests_get.side_effect = Exception("Configuration error")

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True
        mock_apprise_obj.urls.return_value = ["valid://url"]

        # This should not raise an exception but should log the error
        notifier = AppriseNotification("dummy_path.toml")

        # Should log the configuration error
        mock_log_failure.assert_called_with(
            "Error processing Apprise/Pushbullet configuration: Configuration error"
        )

        # Should still be enabled because we have valid URLs
        self.assertTrue(notifier.enabled)

    @patch("apprise_notification.ff_logging.log_failure")
    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_apprise_url_add_failure(
        self, mock_load_config, MockGlobalApprise, mock_log_failure
    ):
        """Test failure to add URL to Apprise object (line 165)."""
        # Setup config with URLs
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=["invalid://url", "valid://url"]),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config

        # Mock Apprise to fail adding one URL but succeed with another
        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.side_effect = [False, True]  # First fails, second succeeds
        mock_apprise_obj.urls.return_value = ["valid://url"]

        notifier = AppriseNotification("dummy_path.toml")

        # Should log failure for one of the URLs (order unpredictable due to set)
        # Check that at least one failure call was made with the expected pattern
        failure_calls = [
            call
            for call in mock_log_failure.call_args_list
            if "Failed to add Apprise URL:" in str(call)
        ]
        self.assertTrue(
            len(failure_calls) > 0, "Should log at least one URL addition failure"
        )

        # Verify the failure message contains one of our URLs
        failure_message = str(failure_calls[0])
        self.assertTrue(
            "invalid://url" in failure_message or "valid://url" in failure_message,
            f"Failure message should contain one of our test URLs: {failure_message}",
        )

        # Should still be enabled because one URL was successful
        self.assertTrue(notifier.enabled)

    @patch("apprise_notification.ff_logging.log_failure")
    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_no_valid_urls_after_processing(
        self, mock_load_config, MockGlobalApprise, mock_log_failure
    ):
        """Test when no URLs are valid after processing (lines 177-181)."""
        # Setup config with URLs that will all fail
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=["invalid://url1", "invalid://url2"]),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config

        # Mock Apprise to fail adding all URLs
        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = False
        mock_apprise_obj.urls.return_value = []  # No valid URLs

        notifier = AppriseNotification("dummy_path.toml")

        # Should log that Apprise is disabled due to no valid URLs
        mock_log_failure.assert_called_with(
            "Apprise configured with URLs, but none could be successfully added to Apprise. "
            "Apprise disabled."
        )

        # Should be disabled
        self.assertFalse(notifier.enabled)

    @patch("apprise_notification.ff_logging.log")
    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_no_urls_configured(self, mock_load_config, MockGlobalApprise, mock_log):
        """Test when no URLs are configured at all (line 255)."""
        # Setup config with no URLs and Pushbullet disabled
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=[]),  # Empty URLs
            pushbullet=PushbulletConfig(enabled=False),  # Disabled Pushbullet
        )
        mock_load_config.return_value = mock_config

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.urls.return_value = []

        notifier = AppriseNotification("dummy_path.toml")

        # Should log that no URLs are configured
        mock_log.assert_called_with(
            "No Apprise URLs configured (including auto-added Pushbullet). Apprise disabled."
        )

        # Should be disabled
        self.assertFalse(notifier.enabled)


class TestAppriseNotificationAdditionalCoverage(unittest.TestCase):
    """Additional tests for edge cases to achieve complete coverage."""

    @patch("apprise_notification.ff_logging.log_debug")
    @patch("apprise_notification.requests.get")
    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_pushbullet_device_found_success(
        self, mock_load_config, MockGlobalApprise, mock_requests_get, mock_log_debug
    ):
        """Test successful Pushbullet device resolution (lines 128-130)."""
        # Setup config with device that will be found
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=[]),
            pushbullet=PushbulletConfig(
                enabled=True, api_key="test_api_key", device="target_device"
            ),
        )
        mock_load_config.return_value = mock_config

        # Mock requests.get to return the target device
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "devices": [
                {
                    "iden": "device1",
                    "active": True,
                    "pushable": True,
                    "nickname": "other_device",
                },
                {
                    "iden": "device2",
                    "active": True,
                    "pushable": True,
                    "nickname": "target_device",
                },
            ]
        }
        mock_requests_get.return_value = mock_response

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True
        mock_apprise_obj.urls.return_value = ["pbul://test_api_key/device2"]

        notifier = AppriseNotification("dummy_path.toml")

        # Should log successful device resolution
        mock_log_debug.assert_any_call("Found device ID: device2")
        self.assertTrue(notifier.enabled)

    @patch("apprise_notification.ff_logging.log_debug")
    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_pushbullet_url_already_present(
        self, mock_load_config, MockGlobalApprise, mock_log_debug
    ):
        """Test when Pushbullet URL is already in Apprise config (line 144)."""
        # Setup config where Pushbullet URL is already in apprise.urls
        pb_url = "pbul://test_api_key"  # Fixed URL format
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=[pb_url]),  # Already contains Pushbullet URL
            pushbullet=PushbulletConfig(
                enabled=True, api_key="test_api_key", device=""  # No device specified
            ),
        )
        mock_load_config.return_value = mock_config

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True
        mock_apprise_obj.urls.return_value = [pb_url]

        notifier = AppriseNotification("dummy_path.toml")

        # Should log that URL was already present
        mock_log_debug.assert_any_call(
            f"Pushbullet URL {pb_url} was already present in Apprise config."
        )
        self.assertTrue(notifier.enabled)

    @patch("apprise_notification.apprise.Apprise")
    @patch("config_models.ConfigManager.load_config")
    def test_is_enabled_method_coverage(self, mock_load_config, MockGlobalApprise):
        """Test is_enabled() method for line coverage (line 255)."""
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=["test://url"]),
            pushbullet=PushbulletConfig(enabled=False),
        )
        mock_load_config.return_value = mock_config

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True
        mock_apprise_obj.urls.return_value = ["test://url"]

        notifier = AppriseNotification("dummy_path.toml")

        # Test is_enabled() method
        result = notifier.is_enabled()
        self.assertEqual(result, notifier.enabled)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main(argv=["first-arg-is-ignored"], exit=False)
