from typing import NamedTuple, Optional, Type
import unittest
from unittest.mock import call, MagicMock, patch

from parameterized import parameterized
import requests

import discord_notification
from discord_notification import DiscordNotification


class TestDiscordNotification(unittest.TestCase):
    class InitTestCase(NamedTuple):
        enabled: bool
        webhook_url: str
        expected_enabled: bool

    @parameterized.expand(
        [
            InitTestCase(
                enabled=True,
                webhook_url="https://discord.com/api/webhooks/valid_webhook",
                expected_enabled=True,
            ),
            InitTestCase(
                enabled=True,
                webhook_url="",
                expected_enabled=False,
            ),
            InitTestCase(
                enabled=False,
                webhook_url="https://discord.com/api/webhooks/valid_webhook",
                expected_enabled=False,
            ),
        ]
    )
    @patch("discord_notification.ff_logging.log_failure")
    @patch("discord_notification.notification_base.tomllib.load")
    @patch("builtins.open", new_callable=MagicMock)
    def test_init(
        self,
        enabled,
        webhook_url,
        expected_enabled,
        mock_open,
        mock_load,
        mock_log_failure,
    ):
        mock_load.return_value = {
            "discord": {
                "enabled": enabled,
                "webhook_url": webhook_url,
            }
        }

        discord_notification_instance = DiscordNotification("path/to/config.toml")

        self.assertEqual(discord_notification_instance.enabled, expected_enabled)

        if not webhook_url and enabled:
            mock_log_failure.assert_called_once_with(
                "Discord webhook URL is missing in the config file. Cannot send notifications."
            )
        else:
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
            SendingNotificationTestCase(
                title="title1",
                body="body1",
                site="site1",
                side_effect=None,
                enabled=True,
                log_called=True,
                log_failure_called=False,
            ),
            SendingNotificationTestCase(
                title="title2",
                body="body2",
                site="site2",
                side_effect=requests.exceptions.RequestException,
                enabled=True,
                log_called=True,
                log_failure_called=True,
            ),
        ]
    )
    @patch("discord_notification.requests.post")
    @patch("discord_notification.ff_logging.log_failure")
    @patch("discord_notification.ff_logging.log")
    @patch("discord_notification.notification_base.tomllib.load")
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
        mock_post,
    ):
        mock_load.return_value = {
            "discord": {
                "enabled": enabled,
                "webhook_url": "https://discord.com/api/webhooks/valid_webhook",
            }
        }
        discord_notification_instance = DiscordNotification("path/to/config.toml")
        discord_notification_instance.enabled = enabled
        mock_post.return_value.raise_for_status.return_value = None
        mock_post.side_effect = side_effect

        discord_notification.notification_base.kSleepTime = 0
        max_attempts = discord_notification.notification_base.kMaxAttempts

        discord_notification_instance.send_notification(title, body, site)

        if log_called:
            expected_call = call(
                f"\t({site}) Sending Discord notification: {title} - {body}",
                "OKGREEN",
            )
            mock_log.assert_has_calls(
                [expected_call] * (max_attempts if log_failure_called else 1)
            )
        else:
            mock_log.assert_not_called()

        if log_failure_called:
            self.assertEqual(mock_log_failure.call_count, max_attempts)
            for i in range(max_attempts):
                self.assertTrue(
                    "\tFailed to send Discord notification:"
                    in mock_log_failure.call_args_list[i][0][0]
                )
        else:
            mock_log_failure.assert_not_called()


if __name__ == "__main__":
    unittest.main()