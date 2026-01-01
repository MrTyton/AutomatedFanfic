from parameterized import parameterized
import unittest
from unittest.mock import patch, MagicMock
import multiprocessing as mp
import time


from services.url_ingester import EmailInfo, email_watcher
from models.fanfic_info import FanficInfo
from models.config_models import (
    EmailConfig,
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
    def test_email_info_init_basic(
        self, name, email, password, server, mailbox, sleep_time
    ):
        # Create EmailConfig directly
        email_config = EmailConfig(
            email=email,
            password=password,
            server=server,
            mailbox=mailbox,
            sleep_time=sleep_time,
        )

        email_info = EmailInfo(email_config)

        self.assertEqual(email_info.email, email)
        self.assertEqual(email_info.password, password)
        self.assertEqual(email_info.server, server)
        self.assertEqual(email_info.mailbox, mailbox)
        self.assertEqual(email_info.sleep_time, sleep_time)

    @parameterized.expand(
        [
            ("no_sites_disabled", []),
            ("ffnet_disabled", ["fanfiction"]),
            ("multiple_sites_disabled", ["fanfiction", "archiveofourown"]),
        ]
    )
    def test_email_info_init_disabled_sites(self, name, disabled_sites):
        # Create EmailConfig directly with disabled_sites setting
        email_config = EmailConfig(
            email="testuser",
            password="test_password",
            server="test_server",
            disabled_sites=disabled_sites,
        )

        email_info = EmailInfo(email_config)

        self.assertEqual(email_info.disabled_sites, disabled_sites)

    @parameterized.expand(
        [
            ("scenario_1", ["url1", "url2"]),
            ("scenario_2", ["url3", "url4", "url5"]),
            ("empty_urls", []),
        ]
    )
    @patch("services.url_ingester.geturls.get_urls_from_imap")
    def test_email_info_get_urls(self, name, expected_urls, mock_get_urls_from_imap):
        # Create EmailConfig directly
        email_config = EmailConfig(
            email="testuser",
            password="test_password",
            server="test_server",
            mailbox="test_mailbox",
            sleep_time=10,
        )

        # Setup mock URL return
        mock_get_urls_from_imap.return_value = expected_urls

        email_info = EmailInfo(email_config)
        result = email_info.get_urls()

        self.assertEqual(result, set(expected_urls))
        mock_get_urls_from_imap.assert_called_once()

    @patch("services.url_ingester.geturls.get_urls_from_imap")
    def test_email_info_get_urls_exception_handling(self, mock_get_urls_from_imap):
        """Test that get_urls handles exceptions gracefully."""
        # Create EmailConfig directly
        email_config = EmailConfig(
            email="testuser",
            password="test_password",
            server="test_server",
            mailbox="test_mailbox",
            sleep_time=10,
        )

        # Setup mock to raise exception
        mock_get_urls_from_imap.side_effect = Exception("Connection failed")

        email_info = EmailInfo(email_config)

        with patch("services.url_ingester.ff_logging.log_failure") as mock_log_failure:
            result = email_info.get_urls()

        # Should return empty set on exception
        self.assertEqual(result, set())
        mock_log_failure.assert_called_once_with(
            "Failed to get URLs: Connection failed"
        )


class TestEmailWatcher(unittest.TestCase):
    """Test the email_watcher main loop function."""

    def setUp(self):
        """Set up common test fixtures."""
        self.mock_email_info = MagicMock()
        self.mock_email_info.sleep_time = 1  # Short sleep for testing
        self.mock_email_info.disabled_sites = []

        self.mock_notification_info = MagicMock()

        self.ingress_queue = mp.Queue()

        # Mock URL parsers for testing
        self.mock_url_parsers = {
            "fanfiction": (MagicMock(), "https://www.fanfiction.net/s/"),
            "archiveofourown": (MagicMock(), "https://archiveofourown.org/works/"),
            "other": (MagicMock(), ""),
        }

    def assert_ingress_has_item(self, expected_fanfic=None, timeout=1.0):
        """Assert that ingress queue has an item, with retry logic for race conditions.

        Args:
            expected_fanfic (FanficInfo, optional): Expected fanfic object to compare
            timeout (float): Maximum time to wait for queue to have items

        Returns:
            FanficInfo: The retrieved fanfic object
        """
        queue = self.ingress_queue
        start_time = time.time()

        while time.time() - start_time < timeout:
            if not queue.empty():
                try:
                    retrieved_fanfic = queue.get_nowait()
                    if expected_fanfic is not None:
                        self.assertEqual(
                            retrieved_fanfic,
                            expected_fanfic,
                            "Retrieved fanfic should equal expected fanfic",
                        )
                    return retrieved_fanfic
                except Exception:
                    pass
            time.sleep(0.001)

        self.fail(f"Ingress queue was empty after {timeout}s timeout.")

    @patch("services.url_ingester.time.sleep")
    @patch("services.url_ingester.regex_parsing.generate_FanficInfo_from_url")
    @patch("services.url_ingester.ff_logging.log")
    def test_email_watcher_processes_urls(
        self, mock_log, mock_generate_fanfic, mock_sleep
    ):
        """Test that email_watcher processes URLs and routes them to queues."""
        # Setup mock to return URLs then stop after one iteration
        self.mock_email_info.get_urls.side_effect = [
            ["https://www.fanfiction.net/s/12345/1/Test-Story"],
            KeyboardInterrupt(),  # Stop the infinite loop
        ]

        # Setup fanfic generation
        mock_fanfic = FanficInfo(
            site="fanfiction", url="https://www.fanfiction.net/s/12345/1/Test-Story"
        )
        mock_generate_fanfic.return_value = mock_fanfic

        # Run email_watcher until KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            email_watcher(
                self.mock_email_info,
                self.mock_notification_info,
                self.ingress_queue,
                self.mock_url_parsers,
            )

        # Verify URL was processed
        mock_generate_fanfic.assert_called_once_with(
            "https://www.fanfiction.net/s/12345/1/Test-Story", self.mock_url_parsers
        )

        # Verify logging
        # Verify logging
        mock_log.assert_called_once_with(
            f"Adding {mock_fanfic.url} to the ingestion queue (Site: {mock_fanfic.site})"
        )

        # Verify fanfic was added to ingress queue
        self.assert_ingress_has_item(mock_fanfic)

    @patch("services.url_ingester.time.sleep")
    @patch("services.url_ingester.regex_parsing.generate_FanficInfo_from_url")
    def test_email_watcher_disabled_sites_notification_only(
        self, mock_generate_fanfic, mock_sleep
    ):
        """Test that disabled site URLs only send notifications when site is in disabled_sites."""
        # Enable FFNet disable mode by adding it to disabled_sites
        self.mock_email_info.disabled_sites = ["fanfiction"]
        self.mock_email_info.get_urls.side_effect = [
            ["https://www.fanfiction.net/s/12345/1/Test-Story"],
            KeyboardInterrupt(),  # Stop the infinite loop
        ]

        # Setup fanfic generation for FFNet
        mock_fanfic = FanficInfo(
            site="fanfiction", url="https://www.fanfiction.net/s/12345/1/Test-Story"
        )
        mock_generate_fanfic.return_value = mock_fanfic

        # Run email_watcher until KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            email_watcher(
                self.mock_email_info,
                self.mock_notification_info,
                self.ingress_queue,
                self.mock_url_parsers,
            )

        # Verify notification was sent
        self.mock_notification_info.send_notification.assert_called_once_with(
            "New Fanfiction Download", mock_fanfic.url, mock_fanfic.site
        )

        # Verify fanfic was NOT added to ingress queue
        self.assertTrue(self.ingress_queue.empty())

    @patch("services.url_ingester.time.sleep")
    @patch("services.url_ingester.regex_parsing.generate_FanficInfo_from_url")
    @patch("services.url_ingester.ff_logging.log")
    def test_email_watcher_multiple_sites(
        self, mock_log, mock_generate_fanfic, mock_sleep
    ):
        """Test that email_watcher routes different sites to appropriate queues."""
        # Setup mock to return URLs from different sites
        self.mock_email_info.get_urls.side_effect = [
            [
                "https://www.fanfiction.net/s/12345/1/FFNet-Story",
                "https://archiveofourown.org/works/67890",
                "https://unknown-site.com/story/999",
            ],
            KeyboardInterrupt(),  # Stop the infinite loop
        ]

        # Setup fanfic generation for different sites
        fanfics = [
            FanficInfo(
                site="fanfiction",
                url="https://www.fanfiction.net/s/12345/1/FFNet-Story",
            ),
            FanficInfo(
                site="archiveofourown",
                url="https://archiveofourown.org/works/67890",
            ),
            FanficInfo(site="other", url="https://unknown-site.com/story/999"),
        ]
        mock_generate_fanfic.side_effect = fanfics

        # Run email_watcher until KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            email_watcher(
                self.mock_email_info,
                self.mock_notification_info,
                self.ingress_queue,
                self.mock_url_parsers,
            )

        # Verify each fanfic was added to the ingress queue (order may vary)
        captured_sites = set()
        for _ in range(3):
            captured_sites.add(self.assert_ingress_has_item().site)

        self.assertEqual(captured_sites, {"fanfiction", "archiveofourown", "other"})

        # Verify logging happened for each fanfic
        self.assertEqual(mock_log.call_count, 3)

    @patch("services.url_ingester.time.sleep")
    def test_email_watcher_empty_urls_cycle(self, mock_sleep):
        """Test that email_watcher handles empty URL responses gracefully."""
        # Setup mock to return empty URLs then stop
        self.mock_email_info.get_urls.side_effect = [
            [],  # No URLs found
            KeyboardInterrupt(),  # Stop the infinite loop
        ]

        # Run email_watcher until KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            email_watcher(
                self.mock_email_info,
                self.mock_notification_info,
                self.ingress_queue,
                self.mock_url_parsers,
            )

        # Verify ingress queue remain empty
        self.assertTrue(self.ingress_queue.empty())

        # Verify no notifications were sent
        self.mock_notification_info.send_notification.assert_not_called()

    @patch("services.url_ingester.time.sleep")
    def test_email_watcher_sleep_timing(self, mock_sleep):
        """Test that email_watcher sleeps for the correct duration."""
        custom_sleep_time = 42
        self.mock_email_info.sleep_time = custom_sleep_time
        self.mock_email_info.get_urls.side_effect = [
            [],  # No URLs found
            KeyboardInterrupt(),  # Stop the infinite loop
        ]

        # Run email_watcher until KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            email_watcher(
                self.mock_email_info,
                self.mock_notification_info,
                self.ingress_queue,
                self.mock_url_parsers,
            )

        # Verify sleep was called with correct duration
        mock_sleep.assert_called_with(custom_sleep_time)


if __name__ == "__main__":
    unittest.main()
