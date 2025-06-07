from parameterized import parameterized
import unittest
from unittest.mock import mock_open, patch, MagicMock, ANY
import multiprocessing as mp

from url_ingester import EmailInfo, email_watcher
from notification_wrapper import (
    NotificationWrapper,
)  # Assuming this is the correct import
from fanfic_info import FanficInfo  # Assuming this is the correct import


class TestUrlIngester(unittest.TestCase):
    @parameterized.expand(
        [
            (
                "path/to/config.toml",
                """
                [email]
                email = "test_email"
                password = "test_password"
                server = "test_server"
                mailbox = "test_mailbox"
                sleep_time = 10
                """,
                {
                    "email": {
                        "email": "test_email",
                        "password": "test_password",
                        "server": "test_server",
                        "mailbox": "test_mailbox",
                        "sleep_time": 10,
                    }
                },
            ),
            (
                "path/to/another_config.toml",
                """
                [email]
                email = "another_test_email"
                password = "another_test_password"
                server = "another_test_server"
                mailbox = "another_test_mailbox"
                sleep_time = 20
                """,
                {
                    "email": {
                        "email": "another_test_email",
                        "password": "another_test_password",
                        "server": "another_test_server",
                        "mailbox": "another_test_mailbox",
                        "sleep_time": 20,
                    }
                },
            ),
        ]
    )
    @patch("builtins.open", new_callable=mock_open)
    def test_email_info_init(self, toml_path, config, expected_config, mock_file):
        mock_file.return_value.read.return_value = str(config).encode()
        email_info = EmailInfo(toml_path)
        self.assertEqual(email_info.email, expected_config["email"]["email"])
        self.assertEqual(email_info.password, expected_config["email"]["password"])
        self.assertEqual(email_info.server, expected_config["email"]["server"])
        self.assertEqual(email_info.mailbox, expected_config["email"]["mailbox"])
        self.assertEqual(email_info.sleep_time, expected_config["email"]["sleep_time"])

    @parameterized.expand(
        [
            (
                "Config with ffnet_disable = true",
                """
                [email]
                email = "test_email"
                password = "test_password"
                server = "test_server"
                mailbox = "test_mailbox"
                ffnet_disable = true
                """,
                True,
            ),
            (
                "Config with ffnet_disable = false",
                """
                [email]
                email = "test_email"
                password = "test_password"
                server = "test_server"
                mailbox = "test_mailbox"
                ffnet_disable = false
                """,
                False,
            ),
            (
                "Config without ffnet_disable (defaulting to True)",
                """
                [email]
                email = "test_email"
                password = "test_password"
                server = "test_server"
                mailbox = "test_mailbox"
                """,
                True,
            ),
        ]
    )
    @patch("builtins.open", new_callable=mock_open)
    def test_email_info_init_ffnet_disable(
        self, name, config_str, expected_ffnet_disable, mock_file
    ):
        mock_file.return_value.read.return_value = config_str.encode()
        email_info = EmailInfo("dummy_path.toml")
        self.assertEqual(email_info.ffnet_disable, expected_ffnet_disable)

    @parameterized.expand(
        [
            (
                """
                [email]
                email = "test_email"
                password = "test_password"
                server = "test_server"
                mailbox = "test_mailbox"
                sleep_time = 10
                """,
                {
                    "email": "test_email",
                    "password": "test_password",
                    "server": "test_server",
                    "mailbox": "test_mailbox",
                },
                ["url1", "url2"],
            ),
            (
                """
                [email]
                email = "another_test_email"
                password = "another_test_password"
                server = "another_test_server"
                mailbox = "another_test_mailbox"
                sleep_time = 20
                """,
                {
                    "email": "another_test_email",
                    "password": "another_test_password",
                    "server": "another_test_server",
                    "mailbox": "another_test_mailbox",
                },
                ["url3", "url4"],
            ),
        ]
    )
    @patch("url_ingester.geturls.get_urls_from_imap")
    @patch("builtins.open", new_callable=mock_open)
    def test_email_info_get_urls(
        self, config, expected_config, urls, mock_file, mock_get_urls_from_imap
    ):
        mock_get_urls_from_imap.return_value = urls
        mock_file.return_value.read.return_value = str(config).encode()
        email_info = EmailInfo("path/to/config.toml")
        result = email_info.get_urls()
        mock_get_urls_from_imap.assert_called_once_with(
            expected_config["server"],
            expected_config["email"],
            expected_config["password"],
            expected_config["mailbox"],
        )
        self.assertEqual(result, urls)


if __name__ == "__main__":
    unittest.main()
