import unittest
from unittest.mock import patch, MagicMock
from notification_base import (
    NotificationBase,
    retry_decorator,
    kSleepTime,
    kMaxAttempts,
)
import tomllib


class TestNotificationBase(unittest.TestCase):
    def setUp(self):
        patcher_open = patch("builtins.open", new_callable=MagicMock)
        patcher_toml_load = patch("tomllib.load", return_value={"key": "value"})

        self.mock_open = patcher_open.start()
        self.mock_toml_load = patcher_toml_load.start()

        self.addCleanup(patcher_open.stop)
        self.addCleanup(patcher_toml_load.stop)

        self.notification = NotificationBase("fake_path")

    def test_initialization(self):
        # Test initialization and config loading
        self.mock_open.assert_called_once_with("fake_path", "rb")
        self.mock_toml_load.assert_called_once()
        self.assertFalse(self.notification.enabled)
        self.assertEqual(self.notification.config, {"key": "value"})

    def test_send_notification_not_implemented(self):
        # Test that send_notification raises NotImplementedError
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
