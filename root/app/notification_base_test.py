import unittest
from unittest.mock import patch, MagicMock
from notification_base import (
    NotificationBase,
    retry_decorator,
    kMaxAttempts,
)


class TestNotificationBase(unittest.TestCase):
    def setUp(self):
        patcher_open = patch("builtins.open", new_callable=MagicMock)
        patcher_toml_load = patch(
            "tomllib.load",
            return_value={
                "notifications": {"apprise_uri": "mock://apprise_uri"}
            },
        )
        patcher_apprise = patch("notification_base.apprise.Apprise")

        self.mock_open = patcher_open.start()
        self.mock_toml_load = patcher_toml_load.start()
        self.mock_apprise = patcher_apprise.start()

        self.addCleanup(patcher_open.stop)
        self.addCleanup(patcher_toml_load.stop)
        self.addCleanup(patcher_apprise.stop)

        self.notification = NotificationBase("fake_path", sleep_time=10)

    def test_initialization(self):
        # Test initialization and config loading
        self.mock_open.assert_called_once_with("fake_path", "rb")
        self.mock_toml_load.assert_called_once()
        self.mock_apprise.assert_called_once()
        self.assertTrue(self.notification.enabled)
        self.assertEqual(
            self.notification.config,
            {"notifications": {"apprise_uri": "mock://apprise_uri"}},
        )

    def test_send_notification(self):
        # Test that send_notification calls the Apprise notify method
        self.notification.enabled = True
        mock_notify = self.mock_apprise.return_value.notify
        mock_notify.return_value = True

        result = self.notification.send_notification("body", "title", "site")

        self.assertTrue(result)
        mock_notify.assert_called_once_with(title="title", body="body")

    def test_send_notification_disabled(self):
        # Test that send_notification returns False if notifications are disabled
        self.notification.enabled = False

        result = self.notification.send_notification("body", "title", "site")

        self.assertFalse(result)

    def test_send_notification_exception(self):
        # Test that send_notification handles exceptions
        self.notification.enabled = True
        mock_notify = self.mock_apprise.return_value.notify
        mock_notify.side_effect = Exception("Test exception")

        result = self.notification.send_notification("body", "title", "site")

        self.assertFalse(result)


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
        # Test that the decorated function is retried if it fails
        mock_func = MagicMock(return_value=False)
        decorated_func = retry_decorator(mock_func)
        decorated_func()
        self.assertEqual(mock_func.call_count, kMaxAttempts)
        self.assertEqual(mock_sleep.call_count, kMaxAttempts - 1)


if __name__ == "__main__":
    unittest.main()
