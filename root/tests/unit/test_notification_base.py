import unittest
from unittest.mock import patch, MagicMock

from notifications.notification_base import (
    NotificationBase,
    retry_decorator,
    kSleepTime,
    kMaxAttempts,
)
from models.config_models import (
    AppConfig,
    EmailConfig,
    CalibreConfig,
    AppriseConfig,
    PushbulletConfig,
)


class TestNotificationBase(unittest.TestCase):
    def setUp(self):
        self.mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )
        self.mock_config_store = MagicMock()
        self.mock_config_store.get.return_value = None
        self.notification = NotificationBase(self.mock_config, self.mock_config_store)

    def test_initialization(self):
        self.assertFalse(self.notification.enabled)
        self.assertEqual(self.notification.config, self.mock_config)

    def test_initialization_with_config_store_overlays_live_fields(self):
        store = MagicMock()
        store_data = {
            "pushbullet.enabled": True,
            "pushbullet.api_key": "live_pb_key",
            "pushbullet.device": "live_device",
            "apprise.urls": ["discord://webhook"],
        }
        store.get.side_effect = lambda key, default=None: store_data.get(key, default)

        notification = NotificationBase(self.mock_config, store)
        assert notification.config is not None
        self.assertTrue(notification.config.pushbullet.enabled)
        self.assertEqual(notification.config.pushbullet.api_key, "live_pb_key")
        self.assertEqual(notification.config.pushbullet.device, "live_device")
        self.assertEqual(notification.config.apprise.urls, ["discord://webhook"])
        # Original AppConfig must not be mutated
        self.assertFalse(self.mock_config.pushbullet.enabled)
        self.assertEqual(self.mock_config.apprise.urls, [])

    def test_send_notification_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            self.notification.send_notification("title", "body", "site")


class TestRetryDecorator(unittest.TestCase):
    @patch("time.sleep", return_value=None)
    def test_retry_decorator_success(self, mock_sleep):
        # Test that the decorated function is called once if it succeeds
        mock_func = MagicMock(return_value=True)
        decorated_func = retry_decorator(mock_func)
        decorated_func()
        mock_func.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("time.sleep", return_value=None)
    def test_retry_decorator_failure(self, mock_sleep):
        # Test that the decorated function is retried up to 3 times if it fails
        mock_func = MagicMock(return_value=False)
        decorated_func = retry_decorator(mock_func)
        decorated_func()
        self.assertEqual(mock_func.call_count, kMaxAttempts)
        self.assertEqual(mock_sleep.call_count, kMaxAttempts - 1)
        for i in range(kMaxAttempts - 1):
            mock_sleep.assert_any_call(kSleepTime * (i + 1))


if __name__ == "__main__":
    unittest.main()
