from parameterized import parameterized
import pickle
import unittest
from unittest.mock import patch, MagicMock
import multiprocessing as mp
import threading
from queue import Empty


from config.config_store import ConfigStore
from services.url_ingester import EmailInfo, email_watcher, _make_fff_get_configuration
from models.fanfic_info import FanficInfo
from models.config_models import (
    EmailConfig,
)


def _subprocess_echo_email(email_info: EmailInfo, result_q) -> None:
    """Top-level helper for test_email_info_picklable_via_spawn_process.
    Must be module-level so it is importable by spawned child processes.
    """
    result_q.put({"email": email_info.email, "server": email_info.server})


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

        email_info = EmailInfo(email_config, ConfigStore({}))

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

        email_info = EmailInfo(email_config, ConfigStore({}))

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

        email_info = EmailInfo(email_config, ConfigStore({}))
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

        email_info = EmailInfo(email_config, ConfigStore({}))

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
        """EmailInfo resolves the ini paths from ConfigStore."""
        store = ConfigStore({})
        if default_ini:
            store.update("calibre.default_ini", default_ini)
        if personal_ini:
            store.update("calibre.personal_ini", personal_ini)
        email_config = EmailConfig(
            email="testuser", password="pass", server="srv", mailbox="INBOX"
        )
        email_info = EmailInfo(email_config, config_store=store)
        self.assertEqual(
            email_info.default_ini, default_ini or store.get_resolved_default_ini()
        )
        self.assertEqual(email_info.personal_ini, personal_ini or "")

    def test_email_info_init_defaults_ini_paths_to_empty_string(self):
        """When no personal_ini set in ConfigStore, personal_ini defaults to empty string."""
        email_config = EmailConfig(
            email="testuser", password="pass", server="srv", mailbox="INBOX"
        )
        email_info = EmailInfo(email_config, ConfigStore({}))
        self.assertEqual(email_info.personal_ini, "")

    @patch("services.url_ingester.geturls.GetURLs")
    def test_email_info_get_urls_without_ini_passes_none_to_geturls(
        self, mock_get_urls_class
    ):
        """Without ini paths configured in ConfigStore, GetURLs is constructed with config=None, get_config=None."""
        email_config = EmailConfig(
            email="testuser", password="pass", server="srv", mailbox="INBOX"
        )
        mock_get_urls_class.return_value.get_urls_from_imap.return_value = []
        store = ConfigStore({})
        email_info = EmailInfo(email_config, config_store=store)
        email_info.get_urls()
        mock_get_urls_class.assert_called_once_with(config=None, get_config=None)

    @patch("services.url_ingester.geturls.GetURLs")
    def test_email_info_get_urls_with_ini_passes_get_config_to_geturls(
        self, mock_get_urls_class
    ):
        """With ini paths in ConfigStore, get_urls builds a get_config callable and passes it to GetURLs."""
        email_config = EmailConfig(
            email="testuser", password="pass", server="srv", mailbox="INBOX"
        )
        mock_get_urls_class.return_value.get_urls_from_imap.return_value = []

        store = ConfigStore({})
        store.update("calibre.default_ini", "/a/defaults.ini")
        store.update("calibre.personal_ini", "/a/personal.ini")

        email_info = EmailInfo(email_config, config_store=store)
        email_info.get_urls()

        # GetURLs constructed with both config= and get_config= populated
        mock_get_urls_class.assert_called_once_with(
            config=mock_get_urls_class.call_args[1]["config"],
            get_config=store.get_fff_configuration,
        )

    @patch("services.url_ingester.geturls.GetURLs")
    def test_email_info_get_urls_rebuilds_on_ini_change(self, mock_get_urls_class):
        """GetURLs is rebuilt when ini files have been modified since last build."""
        email_config = EmailConfig(
            email="testuser", password="pass", server="srv", mailbox="INBOX"
        )
        mock_get_urls_class.return_value.get_urls_from_imap.return_value = []

        store = ConfigStore({})
        store.update("calibre.default_ini", "/a/defaults.ini")
        store.update("calibre.personal_ini", "/a/personal.ini")

        with patch("services.url_ingester.os.path.getmtime") as mock_mtime:
            # First call (during __init__ -> _build_geturls): mtime = 1.0
            mock_mtime.return_value = 1.0
            email_info = EmailInfo(email_config, config_store=store)
            assert mock_get_urls_class.call_count == 1

            # ini file changes between polls
            mock_mtime.return_value = 2.0
            email_info.get_urls()

        # GetURLs must have been rebuilt once more for the changed ini
        assert mock_get_urls_class.call_count == 2

    # ------------------------------------------------------------------
    # imap_idle attribute tests
    # ------------------------------------------------------------------

    @patch("services.url_ingester.geturls.GetURLs")
    def test_email_info_init_imap_idle_defaults_false(self, _):
        """imap_idle defaults to False on EmailInfo when not set in config."""
        email_config = EmailConfig(email="u", password="p", server="s")
        email_info = EmailInfo(email_config, ConfigStore({}))
        self.assertFalse(email_info.imap_idle)

    @patch("services.url_ingester.geturls.GetURLs")
    def test_email_info_init_imap_idle_true(self, _):
        """imap_idle is True on EmailInfo when enabled in config."""
        email_config = EmailConfig(email="u", password="p", server="s", imap_idle=True)
        email_info = EmailInfo(email_config, ConfigStore({}))
        self.assertTrue(email_info.imap_idle)

    def test_email_config_imap_idle_field_default_false(self):
        """EmailConfig.imap_idle defaults to False for backward compatibility."""
        config = EmailConfig(email="u", password="p", server="s")
        self.assertFalse(config.imap_idle)

    def test_email_config_imap_idle_field_accepts_true(self):
        """EmailConfig.imap_idle accepts True."""
        config = EmailConfig(email="u", password="p", server="s", imap_idle=True)
        self.assertTrue(config.imap_idle)

    # ------------------------------------------------------------------
    # Pickle / multiprocessing regression (Python 3.15 forkserver fix)
    # EmailInfo._geturls held a non-picklable closure; these tests guard
    # against regressions that would break forkserver / spawn start methods.
    # ------------------------------------------------------------------

    def test_email_info_getstate_excludes_geturls(self):
        """__getstate__ must omit _geturls and _geturls_ini_mtime."""
        email_config = EmailConfig(email="u", password="p", server="s", mailbox="INBOX")
        ei = EmailInfo(email_config, ConfigStore({}))
        state = ei.__getstate__()
        self.assertNotIn("_geturls", state)
        self.assertNotIn("_geturls_ini_mtime", state)

    def test_email_info_getstate_includes_all_config_fields(self):
        """__getstate__ retains every field needed to reconstruct EmailInfo."""
        email_config = EmailConfig(
            email="u",
            password="p",
            server="s",
            mailbox="INBOX",
            sleep_time=30,
            imap_idle=True,
            disabled_sites=["fanfiction"],
        )
        store = ConfigStore({})
        store.update("calibre.default_ini", "/d.ini")
        store.update("calibre.personal_ini", "/p.ini")
        ei = EmailInfo(email_config, config_store=store)
        state = ei.__getstate__()
        for field in (
            "email",
            "password",
            "server",
            "mailbox",
            "sleep_time",
            "imap_idle",
            "disabled_sites",
            "config_store",
        ):
            self.assertIn(
                field, state, msg=f"Field '{field}' missing from __getstate__"
            )

    def test_email_info_setstate_rebuilds_geturls(self):
        """__setstate__ reconstructs _geturls without calling __init__."""
        email_config = EmailConfig(email="u", password="p", server="s", mailbox="INBOX")
        ei = EmailInfo(email_config, ConfigStore({}))
        state = ei.__getstate__()

        ei2 = object.__new__(EmailInfo)  # bypass __init__
        ei2.__setstate__(state)

        self.assertIsNotNone(ei2._geturls)
        self.assertEqual(ei2.email, "u")
        self.assertEqual(ei2.server, "s")

    def test_email_info_pickle_roundtrip_no_ini(self):
        """EmailInfo with no ini paths survives pickle.dumps / pickle.loads."""
        email_config = EmailConfig(
            email="u", password="p", server="s", mailbox="INBOX", sleep_time=15
        )
        ei = EmailInfo(email_config, ConfigStore({}))
        ei2 = pickle.loads(pickle.dumps(ei))
        self.assertEqual(ei2.email, "u")
        self.assertEqual(ei2.server, "s")
        self.assertEqual(ei2.sleep_time, 15)
        self.assertIsNotNone(ei2._geturls)

    @patch("services.url_ingester.geturls.GetURLs")
    def test_email_info_pickle_roundtrip_with_closure(self, mock_geturls):
        """EmailInfo whose _geturls was built from a closure must be picklable.

        This is the direct regression test: before the __getstate__ fix,
        pickle.dumps raised PicklingError because the closure returned by
        _make_fff_get_configuration cannot be serialised.
        """
        mock_geturls.return_value = MagicMock()

        email_config = EmailConfig(email="u", password="p", server="s", mailbox="INBOX")
        store = ConfigStore({})
        store.update("calibre.default_ini", "/d/defaults.ini")
        store.update("calibre.personal_ini", "/p/personal.ini")
        ei = EmailInfo(email_config, config_store=store)

        # Must not raise, even though _geturls holds an unpicklable closure.
        ei2 = pickle.loads(pickle.dumps(ei))
        self.assertEqual(ei2.email, "u")
        self.assertEqual(ei2.default_ini, "/d/defaults.ini")
        self.assertIsNotNone(ei2._geturls)

    def test_email_info_picklable_via_spawn_process(self):
        """EmailInfo must be passable as a Process arg under the 'spawn' start method.

        Regression test for the Python 3.15 forkserver / spawn PicklingError.
        Uses an explicit 'spawn' context so this test catches regressions even
        when the test suite runs with the default 'fork' start method.
        """
        ctx = mp.get_context("spawn")
        email_config = EmailConfig(email="u", password="p", server="s", mailbox="INBOX")
        ei = EmailInfo(email_config, ConfigStore({}))
        result_q = ctx.Queue()
        p = ctx.Process(target=_subprocess_echo_email, args=(ei, result_q))
        p.start()
        p.join(timeout=30)
        self.assertEqual(p.exitcode, 0, "Spawned subprocess exited non-zero")
        result = result_q.get_nowait()
        self.assertEqual(result["email"], "u")
        self.assertEqual(result["server"], "s")


class TestMakeFffGetConfiguration(unittest.TestCase):
    """Tests for _make_fff_get_configuration (FFF issue #1429 compatibility)."""

    def _call(
        self,
        url,
        store=None,
        sections=None,
    ):
        """Helper: patch FFF internals, invoke the factory, call the inner fn."""
        sections = sections or ["www.royalroad.com", "test1.com"]
        store = store if store is not None else ConfigStore({})

        with (
            patch(
                "fanficfare.adapters.getConfigSectionsFor", return_value=sections
            ) as mock_secs,
            patch("fanficfare.configurable.Configuration") as mock_cfg_cls,
        ):
            mock_cfg = MagicMock()
            mock_cfg_cls.return_value = mock_cfg
            fn = _make_fff_get_configuration(store)
            result = fn(url)
            return result, mock_secs, mock_cfg_cls, mock_cfg

    def test_returns_callable(self):
        """Factory always returns a callable regardless of store value."""
        fn = _make_fff_get_configuration(ConfigStore({}))
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
        with (
            patch(
                "fanficfare.adapters.getConfigSectionsFor",
                side_effect=Exception("UnknownSite"),
            ),
            patch("fanficfare.configurable.Configuration") as mock_cfg_cls,
        ):
            mock_cfg_cls.return_value = MagicMock()
            fn = _make_fff_get_configuration(ConfigStore({}))
            fn(url)
        mock_cfg_cls.assert_called_once_with(["test1.com"], "EPUB")

    def test_callable_loads_both_ini_files_when_present(self):
        """Both ini paths configured in ConfigStore are read when both files exist."""
        from config.config_store import ConfigStore

        store = ConfigStore({})
        store.update("calibre.default_ini", "/d/defaults.ini")
        store.update("calibre.personal_ini", "/d/personal.ini")

        with (
            patch(
                "fanficfare.adapters.getConfigSectionsFor", return_value=["test1.com"]
            ),
            patch("fanficfare.configurable.Configuration") as mock_cfg_cls,
            patch("os.path.isfile", return_value=True),
        ):
            mock_cfg = MagicMock()
            mock_cfg_cls.return_value = mock_cfg
            fn = _make_fff_get_configuration(store)
            fn("https://www.royalroad.com/fiction/1/t")
            mock_cfg.read.assert_called_once_with(
                ["/d/defaults.ini", "/d/personal.ini"]
            )

    def test_callable_skips_missing_ini_files(self):
        """config.read is never called when neither ini file exists on disk."""
        from config.config_store import ConfigStore

        store = ConfigStore({})
        store.update("calibre.default_ini", "/missing/defaults.ini")
        store.update("calibre.personal_ini", "/missing/personal.ini")

        with (
            patch(
                "fanficfare.adapters.getConfigSectionsFor", return_value=["test1.com"]
            ),
            patch("fanficfare.configurable.Configuration") as mock_cfg_cls,
            patch("os.path.isfile", return_value=False),
        ):
            mock_cfg = MagicMock()
            mock_cfg_cls.return_value = mock_cfg
            fn = _make_fff_get_configuration(store)
            fn("https://www.royalroad.com/fiction/1/t")
            mock_cfg.read.assert_not_called()

    def test_callable_loads_only_personal_ini_when_default_missing(self):
        """Only the personal.ini is loaded when the defaults file does not exist."""
        from config.config_store import ConfigStore

        store = ConfigStore({})
        store.update("calibre.default_ini", "/missing/defaults.ini")
        store.update("calibre.personal_ini", "/exists/personal.ini")

        with (
            patch(
                "fanficfare.adapters.getConfigSectionsFor", return_value=["test1.com"]
            ),
            patch("fanficfare.configurable.Configuration") as mock_cfg_cls,
            patch("os.path.isfile", side_effect=lambda p: p == "/exists/personal.ini"),
        ):
            mock_cfg = MagicMock()
            mock_cfg_cls.return_value = mock_cfg
            fn = _make_fff_get_configuration(store)
            fn("https://www.royalroad.com/fiction/1/t")
            mock_cfg.read.assert_called_once_with(["/exists/personal.ini"])

    def test_callable_handles_empty_config_store(self):
        """An empty ConfigStore skips config.read when no ini files exist."""
        from config.config_store import ConfigStore

        store = ConfigStore({})
        with (
            patch(
                "fanficfare.adapters.getConfigSectionsFor", return_value=["test1.com"]
            ),
            patch("fanficfare.configurable.Configuration") as mock_cfg_cls,
            patch("os.path.isfile", return_value=False),
        ):
            mock_cfg = MagicMock()
            mock_cfg_cls.return_value = mock_cfg
            fn = _make_fff_get_configuration(store)
            fn("https://www.royalroad.com/fiction/1/t")
            mock_cfg.read.assert_not_called()

    """Test the email_watcher main loop function."""

    def setUp(self):
        """Set up common test fixtures."""
        self.mock_email_info = MagicMock()
        self.mock_email_info.sleep_time = 1  # Short sleep for testing
        self.mock_email_info.disabled_sites = []
        self.mock_email_info.imap_idle = False  # default to polling in existing tests

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
                {},
                False,
                threading.Event(),
                MagicMock(),
                ConfigStore({}),
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
                {},
                False,
                threading.Event(),
                MagicMock(),
                ConfigStore({}),
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
                {},
                False,
                threading.Event(),
                MagicMock(),
                ConfigStore({}),
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
                {},
                False,
                threading.Event(),
                MagicMock(),
                ConfigStore({}),
            )

        # Verify ingress queue remain empty
        self.assert_ingress_empty()

        # Verify no notifications were sent
        self.mock_notification_info.send_notification.assert_not_called()

    def test_email_watcher_sleep_timing(self):
        """Test that email_watcher waits on shutdown_event for the configured sleep_time duration."""
        custom_sleep_time = 42
        self.mock_email_info.sleep_time = custom_sleep_time
        self.mock_email_info.get_urls.side_effect = [
            [],  # No URLs found
            KeyboardInterrupt(),  # Stop the infinite loop
        ]
        mock_shutdown_event = MagicMock(spec=threading.Event)
        mock_shutdown_event.is_set.return_value = False
        mock_shutdown_event.wait.return_value = False

        # Run email_watcher until KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            email_watcher(
                self.mock_email_info,
                self.mock_notification_info,
                self.ingress_queue,
                self.mock_url_parsers,
                {},
                False,
                mock_shutdown_event,
                MagicMock(),
                ConfigStore({}),
            )

        # Verify shutdown_event.wait was called with correct timeout duration
        mock_shutdown_event.wait.assert_called_with(timeout=custom_sleep_time)

    @patch("services.url_ingester.time.sleep")
    @patch("services.url_ingester.regex_parsing.generate_FanficInfo_from_url")
    def test_email_watcher_uses_idle_wait_when_imap_idle_enabled(
        self, mock_generate_fanfic, mock_sleep
    ):
        """When imap_idle=True, email_watcher calls _idle_wait_for_notification instead of sleep."""
        self.mock_email_info.imap_idle = True
        # _idle_wait_for_notification returns True (new mail available)
        self.mock_email_info._idle_wait_for_notification.return_value = True
        self.mock_email_info.get_urls.side_effect = [
            [],  # First iteration: no URLs
            KeyboardInterrupt(),  # Stop the loop
        ]

        with self.assertRaises(KeyboardInterrupt):
            email_watcher(
                self.mock_email_info,
                self.mock_notification_info,
                self.ingress_queue,
                self.mock_url_parsers,
                {},
                False,
                threading.Event(),
                MagicMock(),
                ConfigStore({}),
            )

        self.mock_email_info._idle_wait_for_notification.assert_called_once()
        mock_sleep.assert_not_called()

    def test_email_watcher_idle_shutdown_signal_breaks_loop(self):
        """When _idle_wait_for_notification returns False, the loop exits cleanly."""
        self.mock_email_info.imap_idle = True
        self.mock_email_info.get_urls.return_value = []
        # Returning False from IDLE wait means shutdown was signalled
        self.mock_email_info._idle_wait_for_notification.return_value = False

        shutdown_event = threading.Event()
        email_watcher(
            self.mock_email_info,
            self.mock_notification_info,
            self.ingress_queue,
            self.mock_url_parsers,
            {},
            False,
            shutdown_event,
            MagicMock(),
            ConfigStore({}),
        )

        self.mock_email_info._idle_wait_for_notification.assert_called_once_with(
            shutdown_event
        )


class TestEmailInfoIdleWait(unittest.TestCase):
    """Tests for EmailInfo._idle_wait_for_notification (IMAP IDLE mode)."""

    def _make_email_info(self):
        email_config = EmailConfig(
            email="testuser",
            password="test_password",
            server="imap.example.com",
            mailbox="INBOX",
            imap_idle=True,
        )
        with patch("services.url_ingester.geturls.GetURLs"):
            return EmailInfo(email_config, ConfigStore({}))

    def _setup_mock_conn(self, mock_cls):
        mock_conn = mock_cls.return_value.__enter__.return_value
        mock_conn.search.return_value = []
        return mock_conn

    @patch("imapclient.IMAPClient")
    def test_returns_true_when_unseen_messages_exist_before_idle(self, mock_cls):
        """If unread messages exist in mailbox upon connection, returns True immediately without entering IDLE."""
        mock_conn = mock_cls.return_value.__enter__.return_value
        mock_conn.search.return_value = [101]

        result = self._make_email_info()._idle_wait_for_notification(threading.Event())

        self.assertTrue(result)
        mock_conn.search.assert_called_once_with("UNSEEN")
        mock_conn.idle.assert_not_called()

    @patch("imapclient.IMAPClient")
    def test_returns_true_on_exists_notification(self, mock_cls):
        """EXISTS response triggers return True so get_urls() is called."""
        mock_conn = self._setup_mock_conn(mock_cls)
        mock_conn.idle_check.return_value = [(12, b"EXISTS")]

        result = self._make_email_info()._idle_wait_for_notification(threading.Event())

        self.assertTrue(result)
        mock_conn.idle.assert_called_once()
        mock_conn.idle_done.assert_called_once()

    @patch("imapclient.IMAPClient")
    def test_returns_true_on_recent_notification(self, mock_cls):
        """RECENT response also triggers return True."""
        mock_conn = self._setup_mock_conn(mock_cls)
        mock_conn.idle_check.return_value = [(5, b"RECENT")]

        result = self._make_email_info()._idle_wait_for_notification(threading.Event())

        self.assertTrue(result)

    @patch("imapclient.IMAPClient")
    def test_returns_false_on_shutdown_before_idle_check(self, mock_cls):
        """Shutdown event set before idle_check causes immediate False return."""
        shutdown_event = threading.Event()
        shutdown_event.set()
        mock_conn = self._setup_mock_conn(mock_cls)

        result = self._make_email_info()._idle_wait_for_notification(shutdown_event)

        self.assertFalse(result)
        mock_conn.idle_check.assert_not_called()
        mock_conn.idle_done.assert_called_once()

    @patch("imapclient.IMAPClient")
    def test_returns_false_on_shutdown_during_idle_check(self, mock_cls):
        """Shutdown event set inside idle_check causes False return after idle_done."""
        shutdown_event = threading.Event()

        def idle_check_side_effect(timeout):
            shutdown_event.set()  # signal shutdown while waiting
            return []  # no new mail

        mock_conn = self._setup_mock_conn(mock_cls)
        mock_conn.idle_check.side_effect = idle_check_side_effect

        result = self._make_email_info()._idle_wait_for_notification(shutdown_event)

        self.assertFalse(result)
        mock_conn.idle_done.assert_called_once()

    @patch("services.url_ingester.ff_logging.log_failure")
    @patch("imapclient.IMAPClient")
    def test_returns_true_and_logs_on_connection_error(
        self, mock_cls, mock_log_failure
    ):
        """Exception during IDLE is caught, logged, and True is returned so get_urls() runs."""
        mock_cls.return_value.__enter__.side_effect = Exception("Connection refused")

        result = self._make_email_info()._idle_wait_for_notification(threading.Event())

        self.assertTrue(result)
        mock_log_failure.assert_called_once()

    @patch("services.url_ingester.time.monotonic")
    @patch("imapclient.IMAPClient")
    def test_reissues_idle_after_9_minutes(self, mock_cls, mock_monotonic):
        """When 9 minutes elapse without notification, returns True so get_urls() runs as a safety fallback."""
        mock_monotonic.side_effect = [0.0, 541.0]

        mock_conn = self._setup_mock_conn(mock_cls)
        mock_conn.idle_check.return_value = []  # no mail signalled during IDLE

        result = self._make_email_info()._idle_wait_for_notification(threading.Event())

        self.assertTrue(result)
        mock_conn.idle.assert_called_once()
        mock_conn.idle_done.assert_called_once()

    @patch("services.url_ingester.time.monotonic")
    @patch("imapclient.IMAPClient")
    def test_idle_refresh_calls_idle_done_and_returns_true(
        self, mock_cls, mock_monotonic
    ):
        """When 9-minute refresh timeout is reached, idle_done is called and True is returned."""
        mock_monotonic.side_effect = [0.0, 545.0]

        mock_conn = self._setup_mock_conn(mock_cls)
        mock_conn.idle_check.return_value = []

        result = self._make_email_info()._idle_wait_for_notification(threading.Event())

        self.assertTrue(result)
        mock_conn.idle_done.assert_called_once()

    def test_update_from_config_store_syncs_ini_paths(self):
        """EmailInfo.update_from_config_store hot-reloads calibre.default_ini and calibre.personal_ini."""
        import os
        import tempfile

        init_store = ConfigStore({})
        email_config = EmailConfig(email="u", password="p", server="s")
        ei = EmailInfo(email_config, init_store)
        self.assertEqual(ei.default_ini, init_store.get_resolved_default_ini())
        self.assertEqual(ei.personal_ini, "")

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ConfigStore({})
            store.update("calibre.default_ini", tmp_dir)
            store.update("calibre.personal_ini", os.path.join(tmp_dir, "personal.ini"))

            with patch.object(ei, "_build_geturls") as mock_rebuild:
                changed = ei.update_from_config_store(store)

            self.assertTrue(changed)
            self.assertEqual(ei.default_ini, os.path.join(tmp_dir, "defaults.ini"))
            self.assertEqual(ei.personal_ini, os.path.join(tmp_dir, "personal.ini"))
            mock_rebuild.assert_called_once()

    def test_email_watcher_reingests_cancelled_url(self):
        """email_watcher must allow re-ingesting a URL whose active_urls entry has status='cancelled'."""
        import re
        from queue import Queue

        email_config = EmailConfig(email="u", password="p", server="s", sleep_time=1)
        store = ConfigStore({})
        ei = EmailInfo(email_config, store)
        mock_notif = MagicMock()
        ingress_q = Queue()
        url_parsers = {
            "archiveofourown": (
                re.compile(r"(archiveofourown\.org/works/\d+)"),
                "",
            )
        }
        # Simulate a URL that was previously cancelled via cancel-retry
        active_urls = {
            "archiveofourown.org/works/12345": {
                "site": "archiveofourown",
                "status": "cancelled",
            }
        }

        with (
            patch.object(
                ei,
                "get_urls",
                side_effect=[
                    {"https://archiveofourown.org/works/12345"},
                    KeyboardInterrupt,
                ],
            ),
            patch("services.url_ingester.time.sleep", side_effect=KeyboardInterrupt),
        ):
            try:
                email_watcher(
                    ei,
                    mock_notif,
                    ingress_q,
                    url_parsers,
                    active_urls,
                    False,
                    threading.Event(),
                    MagicMock(),
                    store,
                )
            except KeyboardInterrupt:
                pass

        queued = ingress_q.get_nowait()
        self.assertEqual(queued.url, "archiveofourown.org/works/12345")
        self.assertEqual(
            active_urls["archiveofourown.org/works/12345"]["status"], "queued"
        )


if __name__ == "__main__":
    unittest.main()
