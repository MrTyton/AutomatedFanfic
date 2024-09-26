from typing import NamedTuple, Optional, Type
import unittest
from unittest.mock import call, MagicMock, patch

from parameterized import parameterized
from pushbullet import InvalidKeyError, PushbulletError

import pushbullet_notification
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
    @patch("pushbullet_notification.notification_base.tomllib.load")
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
            "pushbullet": {
                "enabled": enabled,
                "api_key": api_key,
                "device": device,
            }
        }
        mock_pushbullet.side_effect = (
            side_effect if side_effect else MagicMock()
        )

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
            self.assertTrue(
                "Pushbullet error:" in mock_log_failure.call_args[0][0]
            )
        else:
            mock_log.assert_not_called()
            mock_log_failure.assert_not_called()

    class SendingNotificationTestCase(NamedTuple):
        title: str
        body: str
        site: str
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
                site="site1",
                side_effect=None,
                enabled=True,
                log_called=True,
                log_failure_called=False,
            ),
            # Test case: Pushbullet is enabled but there is a Pushbullet error when sending the notification
            SendingNotificationTestCase(
                title="title2",
                body="body2",
                site="site2",
                side_effect=PushbulletError,
                enabled=True,
                log_called=True,
                log_failure_called=True,
            ),
        ]
    )
    @patch("pushbullet_notification.Pushbullet")
    @patch("pushbullet_notification.ff_logging.log_failure")
    @patch("pushbullet_notification.ff_logging.log")
    @patch("pushbullet_notification.notification_base.tomllib.load")
    @patch("builtins.open", new_callable=MagicMock)
    def test_send_notification(
        self,
        title,
        body,
        site,
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
            "pushbullet": {
                "enabled": enabled,
                "api_key": "valid",
                "device": "device",
            }
        }
        pb_notification = PushbulletNotification("path/to/config.toml")
        pb_notification.pb = mock_pushbullet
        pb_notification.enabled = enabled
        mock_pushbullet.push_note.return_value = None
        mock_pushbullet.push_note.side_effect = side_effect

        pushbullet_notification.notification_base.kSleepTime = 0
        max_attempts = pushbullet_notification.notification_base.kMaxAttempts
        # Execution: Call send_notification
        pb_notification.send_notification(title, body, site)
        # Assertion: Check that the logging functions were called as expected
        if log_called:
            expected_call = call(
                f"\t({site}) Sending Pushbullet notification: {title} - {body}",
                "OKGREEN",
            )

            # Check that the call was made three times
            mock_log.assert_has_calls(
                [expected_call] * (max_attempts if log_failure_called else 1)
            )
        else:
            mock_log.assert_not_called()

        if log_failure_called:
            self.assertEqual(mock_log_failure.call_count, max_attempts)
            for i in range(max_attempts):
                self.assertTrue(
                    "\tFailed to send Pushbullet notification:"
                    in mock_log_failure.call_args_list[i][0][0]
                )
        else:
            mock_log_failure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
