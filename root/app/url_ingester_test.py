from parameterized import parameterized
import unittest
from unittest.mock import mock_open, patch, MagicMock, ANY
import multiprocessing as mp

from url_ingester import EmailInfo, email_watcher
from notification_wrapper import NotificationWrapper # Assuming this is the correct import
from regex_parsing import FanficInfo # Assuming this is the correct import


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

    @patch("url_ingester.regex_parsing.generate_FanficInfo_from_url")
    @patch("url_ingester.notification_wrapper.NotificationWrapper")
    @patch("url_ingester.EmailInfo")
    @patch("multiprocessing.Queue") # For older Python versions, it's mp.Queue
    def test_email_watcher_ffnet_disabled_true(
        self, MockQueue, MockEmailInfo, MockNotificationWrapper, mock_generate_fanfic_info
    ):
        # --- Setup Mocks ---
        # Mock EmailInfo instance
        mock_email_instance = MockEmailInfo.return_value
        mock_email_instance.get_urls.return_value = {"https://www.fanfiction.net/s/12345"}
        mock_email_instance.ffnet_disable = True
        mock_email_instance.sleep_time = 0.01 # To make the loop run fast for test

        # Mock NotificationWrapper instance
        mock_notification_instance = MockNotificationWrapper.return_value

        # Mock Queue instance
        mock_queue_instance = MockQueue.return_value

        # Mock processor_queues dictionary
        processor_queues = {"ffnet": mock_queue_instance, "other_site": MockQueue()}


        # Mock FanficInfo object returned by generate_FanficInfo_from_url
        mock_fic_info = FanficInfo(url="https://www.fanfiction.net/s/12345", site="ffnet")
        mock_generate_fanfic_info.return_value = mock_fic_info

        # --- Call the function ---
        # We need to run the watcher in a way that it executes its loop once or twice and then stops.
        # For this test, get_urls will be called, it will find one ffnet url.
        # ffnet_disable is True, so it should notify and not queue.
        # Then it will sleep and loop. We can stop it after the first pass by making get_urls return empty next.

        # Make get_urls return an empty set on the second call to stop the loop gracefully for the test
        mock_email_instance.get_urls.side_effect = [{"https://www.fanfiction.net/s/12345"}, set()]

        email_watcher(mock_email_instance, mock_notification_instance, processor_queues)

        # --- Assertions ---
        mock_email_instance.get_urls.assert_any_call() # Called at least once
        mock_generate_fanfic_info.assert_called_once_with("https://www.fanfiction.net/s/12345")

        mock_notification_instance.send_notification.assert_called_once_with(
            "New Fanfiction Download", "https://www.fanfiction.net/s/12345", "ffnet"
        )
        mock_queue_instance.put.assert_not_called()
        processor_queues["other_site"].put.assert_not_called()

    @patch("url_ingester.regex_parsing.generate_FanficInfo_from_url")
    @patch("url_ingester.notification_wrapper.NotificationWrapper")
    @patch("url_ingester.EmailInfo")
    @patch("multiprocessing.Queue")
    def test_email_watcher_ffnet_disabled_false(
        self, MockQueue, MockEmailInfo, MockNotificationWrapper, mock_generate_fanfic_info
    ):
        # --- Setup Mocks ---
        mock_email_instance = MockEmailInfo.return_value
        mock_email_instance.get_urls.side_effect = [{"https://www.fanfiction.net/s/67890"}, set()]
        mock_email_instance.ffnet_disable = False
        mock_email_instance.sleep_time = 0.01

        mock_notification_instance = MockNotificationWrapper.return_value
        mock_ffnet_queue_instance = MockQueue() # Specific queue for ffnet
        mock_other_queue_instance = MockQueue() # Queue for other sites

        processor_queues = {"ffnet": mock_ffnet_queue_instance, "other_site": mock_other_queue_instance}

        mock_fic_info = FanficInfo(url="https://www.fanfiction.net/s/67890", site="ffnet")
        mock_generate_fanfic_info.return_value = mock_fic_info

        # --- Call the function ---
        email_watcher(mock_email_instance, mock_notification_instance, processor_queues)

        # --- Assertions ---
        mock_email_instance.get_urls.assert_any_call()
        mock_generate_fanfic_info.assert_called_once_with("https://www.fanfiction.net/s/67890")

        # Specific ffnet notification should NOT be called
        mock_notification_instance.send_notification.assert_not_called()

        mock_ffnet_queue_instance.put.assert_called_once_with(mock_fic_info)
        mock_other_queue_instance.put.assert_not_called()

    @patch("url_ingester.regex_parsing.generate_FanficInfo_from_url")
    @patch("url_ingester.notification_wrapper.NotificationWrapper")
    @patch("url_ingester.EmailInfo")
    @patch("multiprocessing.Queue")
    def test_email_watcher_other_site_url(
        self, MockQueue, MockEmailInfo, MockNotificationWrapper, mock_generate_fanfic_info
    ):
        # --- Setup Mocks ---
        mock_email_instance = MockEmailInfo.return_value
        # Test with ffnet_disable True and False to ensure other sites are unaffected
        for ffnet_disable_setting in [True, False]:
            mock_email_instance.reset_mock() # Reset mocks for each iteration
            MockNotificationWrapper.reset_mock()
            mock_generate_fanfic_info.reset_mock()

            mock_email_instance.get_urls.side_effect = [{"https://archiveofourown.org/works/123"}, set()]
            mock_email_instance.ffnet_disable = ffnet_disable_setting
            mock_email_instance.sleep_time = 0.01

            mock_notification_instance = MockNotificationWrapper.return_value
            mock_ao3_queue_instance = MockQueue()
            mock_ffnet_queue_instance = MockQueue() # ffnet queue, should not be used here

            processor_queues = {"ao3": mock_ao3_queue_instance, "ffnet": mock_ffnet_queue_instance}

            mock_fic_info = FanficInfo(url="https://archiveofourown.org/works/123", site="ao3")
            mock_generate_fanfic_info.return_value = mock_fic_info

            # --- Call the function ---
            email_watcher(mock_email_instance, mock_notification_instance, processor_queues)

            # --- Assertions ---
            mock_email_instance.get_urls.assert_any_call()
            mock_generate_fanfic_info.assert_called_once_with("https://archiveofourown.org/works/123")

            # No ffnet-specific notification
            mock_notification_instance.send_notification.assert_not_called()

            mock_ao3_queue_instance.put.assert_called_once_with(mock_fic_info)
            mock_ffnet_queue_instance.put.assert_not_called()


if __name__ == "__main__":
    unittest.main()
