from parameterized import parameterized
import unittest
from unittest.mock import patch, MagicMock
import multiprocessing as mp
import time


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

    @patch("url_ingester.geturls.get_urls_from_imap")
    @patch("config_models.ConfigManager.load_config")
    def test_email_info_get_urls_exception_handling(self, mock_load_config, mock_get_urls_from_imap):
        """Test that get_urls handles exceptions gracefully."""
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

        # Setup mock to raise exception
        mock_get_urls_from_imap.side_effect = Exception("Connection failed")

        email_info = EmailInfo("test_path.toml")
        
        with patch("url_ingester.ff_logging.log_failure") as mock_log_failure:
            result = email_info.get_urls()

        # Should return empty set on exception
        self.assertEqual(result, set())
        mock_log_failure.assert_called_once_with("Failed to get URLs: Connection failed")


class TestEmailWatcher(unittest.TestCase):
    """Test the email_watcher main loop function."""

    def setUp(self):
        """Set up common test fixtures."""
        self.mock_email_info = MagicMock()
        self.mock_email_info.sleep_time = 1  # Short sleep for testing
        self.mock_email_info.ffnet_disable = False
        
        self.mock_notification_info = MagicMock()
        
        self.processor_queues = {
            "fanfiction.net": mp.Queue(),
            "archiveofourown.org": mp.Queue(),
            "other": mp.Queue()
        }

    @patch("url_ingester.time.sleep")
    @patch("url_ingester.regex_parsing.generate_FanficInfo_from_url")
    @patch("url_ingester.ff_logging.log")
    def test_email_watcher_processes_urls(self, mock_log, mock_generate_fanfic, mock_sleep):
        """Test that email_watcher processes URLs and routes them to queues."""
        # Setup mock to return URLs then stop after one iteration
        self.mock_email_info.get_urls.side_effect = [
            ["https://www.fanfiction.net/s/12345/1/Test-Story"],
            KeyboardInterrupt()  # Stop the infinite loop
        ]
        
        # Setup fanfic generation
        mock_fanfic = FanficInfo(
            site="fanfiction.net", 
            url="https://www.fanfiction.net/s/12345/1/Test-Story"
        )
        mock_generate_fanfic.return_value = mock_fanfic

        # Run email_watcher until KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            email_watcher(self.mock_email_info, self.mock_notification_info, self.processor_queues)

        # Verify URL was processed
        mock_generate_fanfic.assert_called_once_with("https://www.fanfiction.net/s/12345/1/Test-Story")
        
        # Verify logging
        mock_log.assert_called_once_with(
            f"Adding {mock_fanfic.url} to the {mock_fanfic.site} processor queue",
            "HEADER"
        )
        
        # Verify fanfic was added to correct queue
        self.assertFalse(self.processor_queues["fanfiction.net"].empty())
        retrieved_fanfic = self.processor_queues["fanfiction.net"].get_nowait()
        self.assertEqual(retrieved_fanfic, mock_fanfic)

    @patch("url_ingester.time.sleep")
    @patch("url_ingester.regex_parsing.generate_FanficInfo_from_url")
    def test_email_watcher_ffnet_disable_notification_only(self, mock_generate_fanfic, mock_sleep):
        """Test that FFNet URLs only send notifications when ffnet_disable is True."""
        # Enable FFNet disable mode
        self.mock_email_info.ffnet_disable = True
        self.mock_email_info.get_urls.side_effect = [
            ["https://www.fanfiction.net/s/12345/1/Test-Story"],
            KeyboardInterrupt()  # Stop the infinite loop
        ]
        
        # Setup fanfic generation for FFNet
        mock_fanfic = FanficInfo(
            site="ffnet", 
            url="https://www.fanfiction.net/s/12345/1/Test-Story"
        )
        mock_generate_fanfic.return_value = mock_fanfic

        # Run email_watcher until KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            email_watcher(self.mock_email_info, self.mock_notification_info, self.processor_queues)

        # Verify notification was sent
        self.mock_notification_info.send_notification.assert_called_once_with(
            "New Fanfiction Download", mock_fanfic.url, mock_fanfic.site
        )
        
        # Verify fanfic was NOT added to any queue (all queues should be empty)
        for queue in self.processor_queues.values():
            self.assertTrue(queue.empty())

    @patch("url_ingester.time.sleep")
    @patch("url_ingester.regex_parsing.generate_FanficInfo_from_url")
    @patch("url_ingester.ff_logging.log")
    def test_email_watcher_multiple_sites(self, mock_log, mock_generate_fanfic, mock_sleep):
        """Test that email_watcher routes different sites to appropriate queues."""
        # Setup mock to return URLs from different sites
        self.mock_email_info.get_urls.side_effect = [
            [
                "https://www.fanfiction.net/s/12345/1/FFNet-Story",
                "https://archiveofourown.org/works/67890",
                "https://unknown-site.com/story/999"
            ],
            KeyboardInterrupt()  # Stop the infinite loop
        ]
        
        # Setup fanfic generation for different sites
        fanfics = [
            FanficInfo(site="fanfiction.net", url="https://www.fanfiction.net/s/12345/1/FFNet-Story"),
            FanficInfo(site="archiveofourown.org", url="https://archiveofourown.org/works/67890"),
            FanficInfo(site="other", url="https://unknown-site.com/story/999")
        ]
        mock_generate_fanfic.side_effect = fanfics

        # Run email_watcher until KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            email_watcher(self.mock_email_info, self.mock_notification_info, self.processor_queues)

        # Verify each fanfic was added to the correct queue
        ffnet_fanfic = self.processor_queues["fanfiction.net"].get_nowait()
        self.assertEqual(ffnet_fanfic.site, "fanfiction.net")
        
        ao3_fanfic = self.processor_queues["archiveofourown.org"].get_nowait()
        self.assertEqual(ao3_fanfic.site, "archiveofourown.org")
        
        other_fanfic = self.processor_queues["other"].get_nowait()
        self.assertEqual(other_fanfic.site, "other")
        
        # Verify logging happened for each fanfic
        self.assertEqual(mock_log.call_count, 3)

    @patch("url_ingester.time.sleep")
    def test_email_watcher_empty_urls_cycle(self, mock_sleep):
        """Test that email_watcher handles empty URL responses gracefully."""
        # Setup mock to return empty URLs then stop
        self.mock_email_info.get_urls.side_effect = [
            [],  # No URLs found
            KeyboardInterrupt()  # Stop the infinite loop
        ]

        # Run email_watcher until KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            email_watcher(self.mock_email_info, self.mock_notification_info, self.processor_queues)

        # Verify all queues remain empty
        for queue in self.processor_queues.values():
            self.assertTrue(queue.empty())
        
        # Verify no notifications were sent
        self.mock_notification_info.send_notification.assert_not_called()

    @patch("url_ingester.time.sleep")
    def test_email_watcher_sleep_timing(self, mock_sleep):
        """Test that email_watcher sleeps for the correct duration."""
        custom_sleep_time = 42
        self.mock_email_info.sleep_time = custom_sleep_time
        self.mock_email_info.get_urls.side_effect = [
            [],  # No URLs found
            KeyboardInterrupt()  # Stop the infinite loop
        ]

        # Run email_watcher until KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            email_watcher(self.mock_email_info, self.mock_notification_info, self.processor_queues)

        # Verify sleep was called with correct duration
        mock_sleep.assert_called_with(custom_sleep_time)


if __name__ == "__main__":
    unittest.main()
