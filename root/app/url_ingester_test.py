from parameterized import parameterized
import unittest
from unittest.mock import patch, MagicMock
import multiprocessing as mp

from url_ingester import EmailInfo, email_watcher
from notification_wrapper import NotificationWrapper
from fanfic_info import FanficInfo
from config_models import (
    AppConfig,
    EmailConfig,
    CalibreConfig,
    AppriseConfig,
    PushbulletConfig,
)


class TestUrlIngester(unittest.TestCase):
    @parameterized.expand(
        [
            (
                "basic_config",
                "testuser",
                "test_password",
                "test_server",
                "test_mailbox",
                10,
            ),
            (
                "different_config",
                "anotheruser",
                "another_password",
                "another_server",
                "another_mailbox",
                20,
            ),
            (
                "minimal_config",
                "minimaluser",
                "min_pass",
                "min_server",
                "INBOX",
                5,
            ),
        ]
    )
    @patch("config_models.ConfigManager.load_config")
    def test_email_info_init_basic(
        self, name, email, password, server, mailbox, sleep_time, mock_load_config
    ):
        # Setup mock config
        mock_config = AppConfig(
            email=EmailConfig(
                email=email,
                password=password,
                server=server,
                mailbox=mailbox,
                sleep_time=sleep_time,
            ),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config

        email_info = EmailInfo("test_path.toml")

        self.assertEqual(email_info.email, email)
        self.assertEqual(email_info.password, password)
        self.assertEqual(email_info.server, server)
        self.assertEqual(email_info.mailbox, mailbox)
        self.assertEqual(email_info.sleep_time, sleep_time)

    @parameterized.expand(
        [
            ("ffnet_enabled", True),
            ("ffnet_disabled", False),
        ]
    )
    @patch("config_models.ConfigManager.load_config")
    def test_email_info_init_ffnet_disable(self, name, ffnet_disable, mock_load_config):
        # Setup mock config with ffnet_disable setting
        mock_config = AppConfig(
            email=EmailConfig(
                email="testuser",
                password="test_password",
                server="test_server",
                ffnet_disable=ffnet_disable,
            ),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config

        email_info = EmailInfo("test_path.toml")

        self.assertEqual(email_info.ffnet_disable, ffnet_disable)

    @parameterized.expand(
        [
            ("scenario_1", ["url1", "url2"]),
            ("scenario_2", ["url3", "url4", "url5"]),
            ("empty_urls", []),
        ]
    )
    @patch("url_ingester.geturls.get_urls_from_imap")
    @patch("config_models.ConfigManager.load_config")
    def test_email_info_get_urls(
        self, name, expected_urls, mock_load_config, mock_get_urls_from_imap
    ):
        # Setup mock config
        mock_config = AppConfig(
            email=EmailConfig(
                email="testuser",
                password="test_password",
                server="test_server",
                mailbox="test_mailbox",
                sleep_time=10,
            ),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config

        # Setup mock URL return
        mock_get_urls_from_imap.return_value = expected_urls

        email_info = EmailInfo("test_path.toml")
        result = email_info.get_urls()

        self.assertEqual(result, expected_urls)
        mock_get_urls_from_imap.assert_called_once()


if __name__ == "__main__":
    unittest.main()
