import pickle
import multiprocessing as mp
import unittest
from unittest.mock import patch, MagicMock

from config.config_store import ConfigStore
from notifications.apprise_notification import AppriseNotification
from parameterized import parameterized
from models.config_models import (
    AppConfig,
    AppriseConfig,
    PushbulletConfig,
    EmailConfig,
    CalibreConfig,
)


def _make_store(config: AppConfig) -> ConfigStore:
    store = ConfigStore({})
    store.initialize_from_config(config)
    return store


def _subprocess_echo_apprise(notifier: AppriseNotification, result_q) -> None:
    """Top-level helper for test_pickle_roundtrip_via_spawn_process.
    Must be module-level so it is importable by spawned child processes.
    """
    result_q.put(
        {
            "enabled": notifier.enabled,
            "has_log_callback": hasattr(notifier.apobj, "_log_callback"),
            "url_count": len(list(notifier.apobj.urls())),
        }
    )


class TestAppriseNotification(unittest.TestCase):
    @parameterized.expand(
        [
            ("single_url", ["url1"], ["url1"]),
            ("multiple_urls", ["url1", "url2"], ["url1", "url2"]),
            (
                "many_urls",
                ["url1", "url2", "url3", "url4"],
                ["url1", "url2", "url3", "url4"],
            ),
        ]
    )
    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_initialization_reads_urls(
        self, name, input_urls, expected_urls, MockGlobalApprise
    ):
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=input_urls),
            pushbullet=PushbulletConfig(),
        )

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True
        mock_apprise_obj.urls.return_value = expected_urls

        notifier = AppriseNotification(mock_config, _make_store(mock_config))

        self.assertTrue(notifier.enabled)
        for url in expected_urls:
            mock_apprise_obj.add.assert_any_call(url)
            self.assertIn(url, notifier.apprise_urls)

    @parameterized.expand(
        [
            ("empty_apprise", AppriseConfig(), PushbulletConfig()),
            ("empty_urls", AppriseConfig(urls=[]), PushbulletConfig()),
        ]
    )
    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_initialization_missing_apprise_section(
        self,
        name,
        apprise_config,
        pushbullet_config,
        MockGlobalApprise,
    ):
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=apprise_config,
            pushbullet=pushbullet_config,
        )

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.urls.return_value = []

        notifier = AppriseNotification(mock_config, _make_store(mock_config))

        self.assertEqual(notifier.apprise_urls, set())
        self.assertFalse(notifier.enabled)
        mock_apprise_obj.add.assert_not_called()

    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_initialization_missing_urls_key(self, MockGlobalApprise):
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.urls.return_value = []

        notifier = AppriseNotification(mock_config, _make_store(mock_config))
        self.assertEqual(notifier.apprise_urls, set())
        self.assertFalse(notifier.enabled)
        mock_apprise_obj.add.assert_not_called()

    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_initialization_empty_urls_list(self, MockGlobalApprise):
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=[]),
            pushbullet=PushbulletConfig(),
        )

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.urls.return_value = []

        notifier = AppriseNotification(mock_config, _make_store(mock_config))
        self.assertEqual(notifier.apprise_urls, set())
        self.assertFalse(notifier.enabled)
        mock_apprise_obj.add.assert_not_called()

    # --- Tests for auto-addition of Pushbullet URL ---
    @parameterized.expand(
        [
            ("no_device", True, "pb_api_key123", "", "pbul://pb_api_key123"),
            ("with_device", True, "pb_api_key456", "my_device", "pbul://pb_api_key456"),
            ("different_token", True, "different_token", "", "pbul://different_token"),
        ]
    )
    @patch("notifications.apprise_notification.requests")
    @patch("notifications.apprise_notification.apprise.Apprise")
    @patch("notifications.apprise_notification.ff_logging")
    def test_init_auto_adds_pushbullet_url(
        self,
        name,
        enabled,
        token,
        device,
        expected_pb_url,
        mock_ff_logging,
        MockGlobalApprise,
        mock_requests,
    ):
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(enabled=enabled, api_key=token, device=device),
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"devices": []}
        mock_requests.get.return_value = mock_response

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True
        mock_apprise_obj.urls.return_value = [expected_pb_url]

        notifier = AppriseNotification(mock_config, _make_store(mock_config))

        self.assertTrue(notifier.enabled)
        mock_apprise_obj.add.assert_called_once_with(expected_pb_url)
        self.assertIn(expected_pb_url, notifier.apprise_urls)
        mock_ff_logging.log_debug.assert_any_call(
            f"Automatically added Pushbullet URL to Apprise: {expected_pb_url}"
        )

    @parameterized.expand(
        [
            ("disabled", False, "pb_api_key", ""),
            ("disabled_with_device", False, "pb_api_key", "device"),
            ("empty_token", False, "", ""),
        ]
    )
    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_init_pushbullet_disabled_scenarios(
        self, name, enabled, token, device, MockGlobalApprise
    ):
        pushbullet_config = PushbulletConfig(enabled=enabled)
        if token:
            pushbullet_config = PushbulletConfig(
                enabled=enabled, api_key=token, device=device
            )

        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),
            pushbullet=pushbullet_config,
        )

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.urls.return_value = []

        notifier = AppriseNotification(mock_config, _make_store(mock_config))
        self.assertFalse(notifier.enabled)
        self.assertEqual(notifier.apprise_urls, set())
        mock_apprise_obj.add.assert_not_called()

    @parameterized.expand(
        [
            (
                "notification_success",
                None,
                "Test Title",
                "Test Body",
                "TestSite",
            ),
            ("different_title", None, "Another Title", "Another Body", "AnotherSite"),
            ("empty_body", None, "Title Only", "", "EmptySite"),
        ]
    )
    @patch("notifications.apprise_notification.apprise.Apprise")
    @patch("notifications.apprise_notification.ff_logging")
    def test_send_notification_success(
        self,
        name,
        expected_result,
        title,
        body,
        site,
        mock_ff_logging,
        MockAppriseClass,
    ):
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=["url1"]),
            pushbullet=PushbulletConfig(),
        )

        mock_apprise_obj_instance = MockAppriseClass.return_value
        mock_apprise_obj_instance.add.return_value = True
        mock_apprise_obj_instance.urls.return_value = ["url1"]
        mock_apprise_obj_instance.notify.return_value = True

        notifier = AppriseNotification(mock_config, _make_store(mock_config))
        self.assertTrue(notifier.enabled)

        result = notifier.send_notification(title, body, site)

        self.assertIsNone(result)
        mock_apprise_obj_instance.add.assert_called_once_with("url1")
        mock_apprise_obj_instance.notify.assert_called_once_with(body=body, title=title)

    @patch("notifications.apprise_notification.apprise.Apprise")
    @patch("notifications.apprise_notification.ff_logging")
    def test_send_notification_failure(self, mock_ff_logging, MockAppriseClass):
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=["url1"]),
            pushbullet=PushbulletConfig(),
        )

        mock_apprise_obj_instance = MockAppriseClass.return_value
        mock_apprise_obj_instance.add.return_value = True
        mock_apprise_obj_instance.urls.return_value = ["url1"]
        mock_apprise_obj_instance.notify.return_value = False

        notifier = AppriseNotification(mock_config, _make_store(mock_config))
        self.assertTrue(notifier.enabled)

        with patch("notifications.notification_base.time.sleep", return_value=None):
            result = notifier.send_notification("Test Title", "Test Body", "TestSite")

        self.assertFalse(result)
        mock_apprise_obj_instance.add.assert_called_once_with("url1")
        self.assertEqual(mock_apprise_obj_instance.notify.call_count, 3)
        mock_apprise_obj_instance.notify.assert_called_with(
            body="Test Body", title="Test Title"
        )
        self.assertEqual(mock_ff_logging.log_failure.call_count, 3)

    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_send_notification_not_enabled(self, MockGlobalApprise):
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.urls.return_value = []

        with patch("notifications.notification_base.time.sleep", return_value=None):
            notifier = AppriseNotification(mock_config, _make_store(mock_config))
            self.assertFalse(notifier.enabled)
            result = notifier.send_notification("Test Title", "Test Body", "TestSite")
            self.assertFalse(result)
            mock_apprise_obj.notify.assert_not_called()

    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_get_service_name(self, MockGlobalApprise):
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )

        notifier = AppriseNotification(mock_config, _make_store(mock_config))
        self.assertEqual(notifier.get_service_name(), "Apprise")


class TestAppriseNotificationFailures(unittest.TestCase):
    """Test failure scenarios and error handling in AppriseNotification."""

    @patch("notifications.apprise_notification.ff_logging.log_debug")
    @patch("notifications.apprise_notification.requests.get")
    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_pushbullet_device_not_found(
        self, MockGlobalApprise, mock_requests_get, mock_log_debug
    ):
        """Test Pushbullet device not found scenario."""
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=[]),
            pushbullet=PushbulletConfig(
                enabled=True, api_key="test_api_key", device="nonexistent_device"
            ),
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "devices": [
                {
                    "iden": "device1",
                    "active": True,
                    "pushable": True,
                    "nickname": "other_device",
                }
            ]
        }
        mock_requests_get.return_value = mock_response

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True
        mock_apprise_obj.urls.return_value = ["pbal://test_api_key"]

        notifier = AppriseNotification(mock_config, _make_store(mock_config))

        mock_requests_get.assert_called_once_with(
            "https://api.pushbullet.com/v2/devices",
            headers={"Access-Token": "test_api_key"},
        )
        self.assertTrue(notifier.enabled)

    @patch("notifications.apprise_notification.ff_logging.log_failure")
    @patch("notifications.apprise_notification.requests.get")
    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_apprise_configuration_exception(
        self, MockGlobalApprise, mock_requests_get, mock_log_failure
    ):
        """Test exception during Apprise configuration processing."""
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=["valid://url"]),
            pushbullet=PushbulletConfig(
                enabled=True,
                api_key="test_api_key",
                device="my_device",
            ),
        )

        mock_requests_get.side_effect = Exception("Configuration error")

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True
        mock_apprise_obj.urls.return_value = ["valid://url"]

        notifier = AppriseNotification(mock_config, _make_store(mock_config))

        mock_log_failure.assert_called_with(
            "Error processing Apprise/Pushbullet configuration: Configuration error"
        )
        self.assertTrue(notifier.enabled)

    @patch("notifications.apprise_notification.ff_logging.log_failure")
    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_apprise_url_add_failure(self, MockGlobalApprise, mock_log_failure):
        """Test failure to add URL to Apprise object."""
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=["invalid://url", "valid://url"]),
            pushbullet=PushbulletConfig(),
        )

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.side_effect = [False, True]
        mock_apprise_obj.urls.return_value = ["valid://url"]

        notifier = AppriseNotification(mock_config, _make_store(mock_config))

        failure_calls = [
            call
            for call in mock_log_failure.call_args_list
            if "Failed to add Apprise URL:" in str(call)
        ]
        self.assertTrue(
            len(failure_calls) > 0, "Should log at least one URL addition failure"
        )

        failure_message = str(failure_calls[0])
        self.assertTrue(
            "invalid://url" in failure_message or "valid://url" in failure_message,
            f"Failure message should contain one of our test URLs: {failure_message}",
        )
        self.assertTrue(notifier.enabled)

    @patch("notifications.apprise_notification.ff_logging.log_failure")
    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_no_valid_urls_after_processing(self, MockGlobalApprise, mock_log_failure):
        """Test when no URLs are valid after processing."""
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=["invalid://url1", "invalid://url2"]),
            pushbullet=PushbulletConfig(),
        )

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = False
        mock_apprise_obj.urls.return_value = []

        notifier = AppriseNotification(mock_config, _make_store(mock_config))

        mock_log_failure.assert_called_with(
            "Apprise configured with URLs, but none could be successfully added to Apprise. "
            "Apprise disabled."
        )
        self.assertFalse(notifier.enabled)

    @patch("notifications.apprise_notification.ff_logging.log")
    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_no_urls_configured(self, MockGlobalApprise, mock_log):
        """Test when no URLs are configured at all."""
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=[]),
            pushbullet=PushbulletConfig(enabled=False),
        )

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.urls.return_value = []

        notifier = AppriseNotification(mock_config, _make_store(mock_config))

        mock_log.assert_called_with(
            "No Apprise URLs configured (including auto-added Pushbullet). Apprise disabled."
        )
        self.assertFalse(notifier.enabled)


class TestAppriseNotificationAdditionalCoverage(unittest.TestCase):
    """Additional tests for edge cases to achieve complete coverage."""

    @patch("notifications.apprise_notification.ff_logging.log_debug")
    @patch("notifications.apprise_notification.requests.get")
    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_pushbullet_device_found_success(
        self, MockGlobalApprise, mock_requests_get, mock_log_debug
    ):
        """Test successful Pushbullet device resolution."""
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=[]),
            pushbullet=PushbulletConfig(
                enabled=True, api_key="test_api_key", device="target_device"
            ),
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "devices": [
                {
                    "iden": "device1",
                    "active": True,
                    "pushable": True,
                    "nickname": "other_device",
                },
                {
                    "iden": "device2",
                    "active": True,
                    "pushable": True,
                    "nickname": "target_device",
                },
            ]
        }
        mock_requests_get.return_value = mock_response

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True
        mock_apprise_obj.urls.return_value = ["pbul://test_api_key/device2"]

        notifier = AppriseNotification(mock_config, _make_store(mock_config))

        mock_log_debug.assert_any_call("Found device ID: device2")
        self.assertTrue(notifier.enabled)

    @patch("notifications.apprise_notification.ff_logging.log_debug")
    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_pushbullet_url_already_present(self, MockGlobalApprise, mock_log_debug):
        """Test when Pushbullet URL is already in Apprise config."""
        pb_url = "pbul://test_api_key"
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=[pb_url]),
            pushbullet=PushbulletConfig(
                enabled=True, api_key="test_api_key", device=""
            ),
        )

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True
        mock_apprise_obj.urls.return_value = [pb_url]

        notifier = AppriseNotification(mock_config, _make_store(mock_config))

        mock_log_debug.assert_any_call(
            f"Pushbullet URL {pb_url} was already present in Apprise config."
        )
        self.assertTrue(notifier.enabled)

    @patch("notifications.apprise_notification.apprise.Apprise")
    def test_is_enabled_method_coverage(self, MockGlobalApprise):
        """Test is_enabled() method for line coverage."""
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(urls=["test://url"]),
            pushbullet=PushbulletConfig(enabled=False),
        )

        mock_apprise_obj = MockGlobalApprise.return_value
        mock_apprise_obj.add.return_value = True
        mock_apprise_obj.urls.return_value = ["test://url"]

        notifier = AppriseNotification(mock_config, _make_store(mock_config))

        result = notifier.is_enabled()
        self.assertEqual(result, notifier.enabled)
        self.assertTrue(result)


class TestAppriseNotificationPickle(unittest.TestCase):
    """Pickle / multiprocessing regression tests for AppriseNotification.

    apprise.Apprise() objects lose private attributes (e.g. _log_callback)
    when pickled. These tests guard against regressions that would break
    the forkserver / spawn start methods used to launch worker processes.
    """

    def _make_notifier(self, urls: list[str], enabled=True):
        """Build an AppriseNotification instance bypassing config loading."""
        import apprise

        obj = object.__new__(AppriseNotification)
        obj.apprise_urls = list(urls)
        obj.apobj = apprise.Apprise()
        for url in obj.apprise_urls:
            obj.apobj.add(url)
        obj.enabled = enabled
        obj.config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
        )
        return obj

    def test_getstate_excludes_apobj(self):
        """__getstate__ must omit the un-picklable Apprise object."""
        notifier = self._make_notifier(["json://localhost"])
        state = notifier.__getstate__()
        self.assertNotIn("apobj", state)

    def test_getstate_includes_essential_fields(self):
        """__getstate__ must retain apprise_urls and enabled."""
        notifier = self._make_notifier(["json://localhost"], enabled=True)
        state = notifier.__getstate__()
        for field in ("apprise_urls", "enabled"):
            self.assertIn(
                field, state, msg=f"Field '{field}' missing from __getstate__"
            )
        self.assertEqual(state["apprise_urls"], ["json://localhost"])
        self.assertTrue(state["enabled"])

    def test_setstate_rebuilds_apobj_with_log_callback(self):
        """__setstate__ must create a fresh Apprise object that has _log_callback."""
        notifier = self._make_notifier(["json://localhost"])
        state = notifier.__getstate__()

        notifier2 = object.__new__(AppriseNotification)
        notifier2.__setstate__(state)

        self.assertTrue(
            hasattr(notifier2.apobj, "_log_callback"),
            "_log_callback missing after __setstate__",
        )

    def test_setstate_restores_urls_to_apobj(self):
        """__setstate__ must re-add all saved URLs to the rebuilt Apprise object."""
        notifier = self._make_notifier(["json://localhost"])
        state = notifier.__getstate__()

        notifier2 = object.__new__(AppriseNotification)
        notifier2.__setstate__(state)

        rebuilt_urls = list(notifier2.apobj.urls())
        self.assertEqual(len(rebuilt_urls), 1)

    def test_pickle_roundtrip_restores_log_callback(self):
        """Regression: _log_callback must be present after pickle round-trip.

        Before the __getstate__/__setstate__ fix, apprise.Apprise() lost its
        private attributes when pickled, causing worker crashes:
            'Apprise' object has no attribute '_log_callback'
        """
        notifier = self._make_notifier(["json://localhost"])
        notifier2 = pickle.loads(pickle.dumps(notifier))
        self.assertTrue(
            hasattr(notifier2.apobj, "_log_callback"),
            "_log_callback missing after pickle round-trip — worker would crash",
        )

    def test_pickle_roundtrip_preserves_enabled_true(self):
        """enabled=True is preserved across a pickle round-trip."""
        notifier = self._make_notifier(["json://localhost"], enabled=True)
        notifier2 = pickle.loads(pickle.dumps(notifier))
        self.assertTrue(notifier2.enabled)
        self.assertEqual(notifier2.apprise_urls, ["json://localhost"])

    def test_pickle_roundtrip_preserves_enabled_false(self):
        """enabled=False (no URLs configured) is preserved across a pickle round-trip."""
        notifier = self._make_notifier(urls=[], enabled=False)
        notifier2 = pickle.loads(pickle.dumps(notifier))
        self.assertFalse(notifier2.enabled)
        self.assertEqual(notifier2.apprise_urls, [])
        self.assertIsNotNone(notifier2.apobj)

    def test_pickle_roundtrip_via_spawn_process(self):
        """AppriseNotification must be passable as a Process arg under 'spawn'.

        Regression test for the forkserver / spawn PicklingError.
        Uses an explicit 'spawn' context so this catches regressions even
        when the test suite itself runs under the default 'fork' start method.
        """
        ctx = mp.get_context("spawn")
        notifier = self._make_notifier(["json://localhost"], enabled=True)
        result_q = ctx.Queue()
        p = ctx.Process(target=_subprocess_echo_apprise, args=(notifier, result_q))
        p.start()
        p.join(timeout=30)
        self.assertEqual(p.exitcode, 0, "Spawned subprocess exited non-zero")
        result = result_q.get_nowait()
        self.assertTrue(result["enabled"])
        self.assertTrue(
            result["has_log_callback"],
            "_log_callback missing inside spawned subprocess",
        )
        self.assertEqual(result["url_count"], 1)


if __name__ == "__main__":
    unittest.main(argv=["first-arg-is-ignored"], exit=False)
