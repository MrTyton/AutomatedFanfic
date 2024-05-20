from typing import NamedTuple, Optional, Type
import unittest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from pushbullet import InvalidKeyError, PushbulletError

from pushbullet_notification import PushbulletNotification


class TestPushbulletNotification(unittest.TestCase):
    class InitTestCase(NamedTuple):
        enabled: bool
        api_key: str
        device: str
        side_effect: Optional[Type[BaseException]]
        expected: bool

    @parameterized.expand(
        [
            # Test case: Pushbullet is enabled and API key is valid, device is specified
            InitTestCase(
                enabled=True,
                api_key="valid_api_key",
                device="device1",
                side_effect=None,
                expected=True,
            ),
            # Test case: Pushbullet is enabled and API key is valid, device is not specified
            InitTestCase(
                enabled=True,
                api_key="valid_api_key",
                device="",
                side_effect=None,
                expected=True,
            ),
            # Test case: Pushbullet is enabled but API key is invalid, device is specified
            InitTestCase(
                enabled=True,
                api_key="invalid_api_key",
                device="device1",
                side_effect=InvalidKeyError,
                expected=False,
            ),
            # Test case: Pushbullet is enabled but there is a Pushbullet error, device is not specified
            InitTestCase(
                enabled=True,
                api_key="valid_api_key",
                device="",
                side_effect=PushbulletError,
                expected=False,
            ),
            # Test case: Pushbullet is disabled, device is specified
            InitTestCase(
                enabled=False,
                api_key="valid_api_key",
                device="device1",
                side_effect=None,
                expected=False,
            ),
        ]
    )
    @patch("pushbullet_notification.Pushbullet")
    @patch("pushbullet_notification.ff_logging.log_failure")
    @patch("pushbullet_notification.ff_logging.log")
    @patch("pushbullet_notification.tomllib.load")
    @patch("builtins.open", new_callable=MagicMock)
    def test_init(
        self,
        enabled,
        api_key,
        device,
        side_effect,
        expected_enabled,
        mock_open,
        mock_load,
        mock_log,
        mock_log_failure,
        mock_pushbullet,
    ):
        # Setup: Mock the configuration and the Pushbullet client
        mock_load.return_value = {
            "pushbullet": {"enabled": enabled, "api_key": api_key, "device": device}
        }
        mock_pushbullet.side_effect = side_effect if side_effect else MagicMock()

        # Execution: Create a PushbulletNotification instance
        pb_notification = PushbulletNotification("path/to/config.toml")

        # Assertion: Check that the 'enabled' attribute is as expected
        self.assertEqual(pb_notification.enabled, expected_enabled)

        # Assertion: Check that the logging functions were called as expected
        if side_effect is InvalidKeyError:
            mock_log_failure.assert_called_once_with(
                "Invalid Pushbullet API key in the config file. Cannot send notifications."
            )
        elif side_effect is PushbulletError:
            mock_log_failure.assert_called_once()
            self.assertTrue("Pushbullet error:" in mock_log_failure.call_args[0][0])
        else:
            mock_log.assert_not_called()
            mock_log_failure.assert_not_called()

    class SendingNotificationTestCase(NamedTuple):
        title: str
        body: str
        side_effect: Optional[Type[BaseException]]
        enabled: bool
        log_called: bool
        log_failure_called: bool

    @parameterized.expand(
        [
            # Test case: Pushbullet is enabled and the notification is sent successfully
            SendingNotificationTestCase(
                title="title1",
                body="body1",
                side_effect=None,
                enabled=True,
                log_called=True,
                log_failure_called=False,
            ),
            # Test case: Pushbullet is enabled but there is a Pushbullet error when sending the notification
            SendingNotificationTestCase(
                title="title2",
                body="body2",
                side_effect=PushbulletError,
                enabled=True,
                log_called=True,
                log_failure_called=True,
            ),
            # Test case: Pushbullet is disabled
            SendingNotificationTestCase(
                title="title3",
                body="body3",
                side_effect=None,
                enabled=False,
                log_called=False,
                log_failure_called=False,
            ),
        ]
    )
    @patch("pushbullet_notification.Pushbullet")
    @patch("pushbullet_notification.ff_logging.log_failure")
    @patch("pushbullet_notification.ff_logging.log")
    @patch("pushbullet_notification.tomllib.load")
    @patch("builtins.open", new_callable=MagicMock)
    def test_send_notification(
        self,
        title,
        body,
        side_effect,
        enabled,
        log_called,
        log_failure_called,
        mock_open,
        mock_load,
        mock_log,
        mock_log_failure,
        mock_pushbullet,
    ):
        # Setup: Create a PushbulletNotification instance with a mock Pushbullet client
        mock_load.return_value = {
            "pushbullet": {"enabled": enabled, "api_key": "valid", "device": "device"}
        }
        pb_notification = PushbulletNotification("path/to/config.toml")
        pb_notification.pb = mock_pushbullet
        pb_notification.enabled = enabled
        mock_pushbullet.push_note.return_value = None
        mock_pushbullet.push_note.side_effect = side_effect

        # Execution: Call send_notification
        pb_notification.send_notification(title, body)
        # Assertion: Check that the logging functions were called as expected
        if log_called:
            mock_log.assert_called_once_with(
                f"\tSending Pushbullet notification: {title} - {body}", "OKBLUE"
            )
        else:
            mock_log.assert_not_called()

        if log_failure_called:
            mock_log_failure.assert_called_once()
            self.assertTrue(
                "\tFailed to send Pushbullet notification:"
                in mock_log_failure.call_args[0][0]
            )
        else:
            mock_log_failure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
