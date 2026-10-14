from parameterized import parameterized
import unittest
from unittest.mock import patch, MagicMock
import multiprocessing as mp
from queue import Empty


from services.url_ingester import EmailInfo, email_watcher, _make_fff_get_configuration
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
    @patch("services.url_ingester.geturls.GetURLs")
    def test_email_info_get_urls(self, name, expected_urls, mock_get_urls_class):
        # Create EmailConfig directly
        email_config = EmailConfig(
            email="testuser",
            password="test_password",
            server="test_server",
            mailbox="test_mailbox",
            sleep_time=10,
        )

        # Setup mock URL return via the class instance
        mock_get_urls_class.return_value.get_urls_from_imap.return_value = expected_urls

        email_info = EmailInfo(email_config)
        result = email_info.get_urls()

        self.assertEqual(result, set(expected_urls))
        mock_get_urls_class.return_value.get_urls_from_imap.assert_called_once()

    @patch("services.url_ingester.geturls.GetURLs")
    def test_email_info_get_urls_exception_handling(self, mock_get_urls_class):
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
        mock_get_urls_class.return_value.get_urls_from_imap.side_effect = Exception(
            "Connection failed"
        )

        email_info = EmailInfo(email_config)

        with patch("services.url_ingester.ff_logging.log_failure") as mock_log_failure:
            result = email_info.get_urls()

        # Should return empty set on exception
        self.assertEqual(result, set())
        mock_log_failure.assert_called_once_with(
            "Failed to get URLs: Connection failed"
        )

    # ------------------------------------------------------------------
    # ini-path kwarg tests (FFF issue #1429)
    # ------------------------------------------------------------------

    @parameterized.expand(
        [
            ("both_paths", "/path/defaults.ini", "/path/personal.ini"),
            ("default_only", "/path/defaults.ini", None),
            ("personal_only", None, "/path/personal.ini"),
        ]
    )
    def test_email_info_init_stores_ini_paths(self, name, default_ini, personal_ini):
        """EmailInfo stores the ini paths passed as kwargs."""
        email_config = EmailConfig(
            email="testuser", password="pass", server="srv", mailbox="INBOX"
        )
        email_info = EmailInfo(
            email_config, default_ini=default_ini, personal_ini=personal_ini
        )
        self.assertEqual(email_info.default_ini, default_ini or "")
        self.assertEqual(email_info.personal_ini, personal_ini or "")

    def test_email_info_init_defaults_ini_paths_to_empty_string(self):
        """When no ini kwargs provided, paths default to empty string."""
        email_config = EmailConfig(
            email="testuser", password="pass", server="srv", mailbox="INBOX"
        )
        email_info = EmailInfo(email_config)
        self.assertEqual(email_info.default_ini, "")
        self.assertEqual(email_info.personal_ini, "")

    @patch("services.url_ingester.geturls.GetURLs")
    def test_email_info_get_urls_without_ini_passes_none_to_geturls(
        self, mock_get_urls_class
    ):
        """Without ini paths GetURLs is constructed with config=None, get_config=None."""
        email_config = EmailConfig(
            email="testuser", password="pass", server="srv", mailbox="INBOX"
        )
        mock_get_urls_class.return_value.get_urls_from_imap.return_value = []
        email_info = EmailInfo(email_config)
        email_info.get_urls()
        mock_get_urls_class.assert_called_once_with(config=None, get_config=None)

    @patch("services.url_ingester.geturls.GetURLs")
    @patch("services.url_ingester._make_fff_get_configuration")
    def test_email_info_get_urls_with_ini_passes_get_config_to_geturls(
        self, mock_make_config, mock_get_urls_class
    ):
        """With ini paths get_urls builds a get_config callable and passes it to GetURLs."""
        email_config = EmailConfig(
            email="testuser", password="pass", server="srv", mailbox="INBOX"
        )

        mock_get_config_fn = MagicMock()
        mock_make_config.return_value = mock_get_config_fn
        mock_initial_config = MagicMock()
        mock_get_config_fn.return_value = mock_initial_config
        mock_get_urls_class.return_value.get_urls_from_imap.return_value = []

        email_info = EmailInfo(
            email_config,
            default_ini="/a/defaults.ini",
            personal_ini="/a/personal.ini",
        )
        email_info.get_urls()

        # _make_fff_get_configuration called with stored ini paths
        mock_make_config.assert_called_once_with("/a/defaults.ini", "/a/personal.ini")
        # Initial config seeded via get_config_fn("test1.com") to avoid chicken-and-egg crash
        mock_get_config_fn.assert_called_once_with("test1.com")
        # GetURLs constructed with both config= and get_config= populated
        mock_get_urls_class.assert_called_once_with(
            config=mock_initial_config, get_config=mock_get_config_fn
        )


class TestMakeFffGetConfiguration(unittest.TestCase):
    """Tests for _make_fff_get_configuration (FFF issue #1429 compatibility)."""

    def _call(
        self,
        url,
        default_ini=None,
        personal_ini=None,
        sections=None,
        isfile_side_effect=None,
    ):
        """Helper: patch FFF internals, invoke the factory, call the inner fn."""
        sections = sections or ["www.royalroad.com", "test1.com"]
        isfile_side_effect = isfile_side_effect or (lambda _: False)

        with patch(
            "fanficfare.adapters.getConfigSectionsFor", return_value=sections
        ) as mock_secs, patch(
            "fanficfare.configurable.Configuration"
        ) as mock_cfg_cls, patch(
            "services.url_ingester.os.path.isfile", side_effect=isfile_side_effect
        ):
            mock_cfg = MagicMock()
            mock_cfg_cls.return_value = mock_cfg
            fn = _make_fff_get_configuration(default_ini, personal_ini)
            result = fn(url)
            return result, mock_secs, mock_cfg_cls, mock_cfg

    def test_returns_callable(self):
        """Factory always returns a callable regardless of ini path values."""
        fn = _make_fff_get_configuration(None, None)
        self.assertTrue(callable(fn))

    def test_callable_uses_sections_from_url(self):
        """get_configuration calls getConfigSectionsFor with the URL."""
        url = "https://www.royalroad.com/fiction/123/test"
        result, mock_secs, mock_cfg_cls, mock_cfg = self._call(
            url, sections=["www.royalroad.com", "test1.com"]
        )
        mock_secs.assert_called_once_with(url)
        mock_cfg_cls.assert_called_once_with(["www.royalroad.com", "test1.com"], "EPUB")
        self.assertIs(result, mock_cfg)

    def test_callable_falls_back_on_unknown_url(self):
        """When getConfigSectionsFor raises, falls back to ['test1.com']."""
        url = "https://not-a-fanfic-site.example.com/story/123"
        with patch(
            "fanficfare.adapters.getConfigSectionsFor",
            side_effect=Exception("UnknownSite"),
        ), patch("fanficfare.configurable.Configuration") as mock_cfg_cls, patch(
            "services.url_ingester.os.path.isfile", return_value=False
        ):
            mock_cfg_cls.return_value = MagicMock()
            fn = _make_fff_get_configuration(None, None)
            fn(url)
        mock_cfg_cls.assert_called_once_with(["test1.com"], "EPUB")

    def test_callable_loads_both_ini_files_when_present(self):
        """Both ini paths are read when both files exist."""
        result, _, _, mock_cfg = self._call(
            "https://www.royalroad.com/fiction/1/t",
            default_ini="/d/defaults.ini",
            personal_ini="/d/personal.ini",
            isfile_side_effect=lambda _: True,
        )
        mock_cfg.read.assert_called_once_with(["/d/defaults.ini", "/d/personal.ini"])

    def test_callable_skips_missing_ini_files(self):
        """config.read is never called when neither ini file exists on disk."""
        result, _, _, mock_cfg = self._call(
            "https://www.royalroad.com/fiction/1/t",
            default_ini="/missing/defaults.ini",
            personal_ini="/missing/personal.ini",
            isfile_side_effect=lambda _: False,
        )
        mock_cfg.read.assert_not_called()

    def test_callable_loads_only_personal_ini_when_default_missing(self):
        """Only the personal.ini is loaded when the defaults file does not exist."""
        result, _, _, mock_cfg = self._call(
            "https://www.royalroad.com/fiction/1/t",
            default_ini="/missing/defaults.ini",
            personal_ini="/exists/personal.ini",
            isfile_side_effect=lambda p: p == "/exists/personal.ini",
        )
        mock_cfg.read.assert_called_once_with(["/exists/personal.ini"])

    def test_callable_handles_none_ini_paths(self):
        """Passing None for both ini paths is safe and skips config.read."""
        result, _, _, mock_cfg = self._call(
            "https://www.royalroad.com/fiction/1/t",
            default_ini=None,
            personal_ini=None,
        )
        mock_cfg.read.assert_not_called()

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

    def tearDown(self):
        self.ingress_queue.close()
        self.ingress_queue.join_thread()

    def assert_ingress_has_item(self, expected_fanfic=None, timeout=1.0):
        """Assert that ingress queue has an item within timeout.

        Args:
            expected_fanfic (FanficInfo, optional): Expected fanfic object to compare
            timeout (float): Maximum time to wait for queue to have items

        Returns:
            FanficInfo: The retrieved fanfic object
        """
        try:
            retrieved_fanfic = self.ingress_queue.get(timeout=timeout)
        except Empty as exc:
            self.fail(f"Ingress queue did not contain an item within {timeout}s: {exc}")

        if expected_fanfic is not None:
            self.assertEqual(
                retrieved_fanfic,
                expected_fanfic,
                "Retrieved fanfic should equal expected fanfic",
            )
        return retrieved_fanfic

    def assert_ingress_empty(self):
        """Assert ingress queue is empty without relying on queue.empty()."""
        try:
            unexpected = self.ingress_queue.get_nowait()
            self.fail(f"Expected empty ingress queue, but found item: {unexpected}")
        except Empty:
            # Expected success path: queue had no pending items.
            pass

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
        self.assert_ingress_empty()

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
        self.assert_ingress_empty()

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
