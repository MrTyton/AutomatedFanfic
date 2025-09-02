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
                enabled=enabled, token=token, device=device
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


if __name__ == "__main__":
    unittest.main(argv=["first-arg-is-ignored"], exit=False)
