"""Tests for Phase 2 pipeline instrumentation — history recording calls.

Verifies that each instrumented function calls the appropriate HistoryRecorder
methods when a recorder is provided.
"""

import threading
import unittest
from queue import Empty
from unittest.mock import MagicMock, patch

from models.config_models import (
    AppConfig,
    AppriseConfig,
    CalibreConfig,
    EmailConfig,
    PushbulletConfig,
    RetryConfig,
)
from models.fanfic_info import FanficInfo
from models import retry_types


class TestEmailWatcherInstrumentation(unittest.TestCase):
    """Tests for email_watcher history recording."""

    def setUp(self):
        self.email_info = MagicMock()
        self.email_info.sleep_time = 0
        self.email_info.disabled_sites = []
        self.email_info.imap_idle = False
        self.notification_info = MagicMock()
        self.ingress_queue = MagicMock()
        self.url_parsers = {}
        self.active_urls = {}
        self.shutdown_event = threading.Event()
        self.recorder = MagicMock()
        self.config_store = MagicMock()

    @patch("services.url_ingester.regex_parsing.generate_FanficInfo_from_url")
    def test_records_email_check_event(self, mock_generate):
        """email_watcher records an EmailCheckEvent after processing URLs."""
        from services.url_ingester import email_watcher

        fanfic = FanficInfo(url="https://archiveofourown.org/works/123", site="ao3")
        mock_generate.return_value = fanfic

        # First call returns URLs, then trigger shutdown
        def get_urls_then_shutdown():
            self.shutdown_event.set()
            return {"https://archiveofourown.org/works/123"}

        self.email_info.get_urls.side_effect = get_urls_then_shutdown

        email_watcher(
            self.email_info,
            self.notification_info,
            self.ingress_queue,
            self.url_parsers,
            self.active_urls,
            False,
            self.shutdown_event,
            self.recorder,
            self.config_store,
        )

        self.recorder.record_email_check.assert_called_once_with(
            urls_found=1,
            urls_new=1,
            urls_duplicate=0,
            urls_disabled_site=0,
            trigger="poll",
        )

    @patch("services.url_ingester.regex_parsing.generate_FanficInfo_from_url")
    def test_records_download_created_for_new_urls(self, mock_generate):
        """email_watcher records download_created for each new URL."""
        from services.url_ingester import email_watcher

        fanfic = FanficInfo(url="https://archiveofourown.org/works/123", site="ao3")
        mock_generate.return_value = fanfic

        def get_urls_then_shutdown():
            self.shutdown_event.set()
            return {"https://archiveofourown.org/works/123"}

        self.email_info.get_urls.side_effect = get_urls_then_shutdown

        email_watcher(
            self.email_info,
            self.notification_info,
            self.ingress_queue,
            self.url_parsers,
            self.active_urls,
            False,
            self.shutdown_event,
            self.recorder,
            self.config_store,
        )

        self.recorder.record_download_created.assert_called_once_with(
            "https://archiveofourown.org/works/123", "ao3", None
        )

    @patch("services.url_ingester.regex_parsing.generate_FanficInfo_from_url")
    def test_counts_disabled_sites(self, mock_generate):
        """email_watcher tracks disabled_site count in email check event."""
        from services.url_ingester import email_watcher

        fanfic = FanficInfo(url="https://fanfiction.net/s/123", site="fanfiction")
        mock_generate.return_value = fanfic
        self.email_info.disabled_sites = ["fanfiction"]

        def get_urls_then_shutdown():
            self.shutdown_event.set()
            return {"https://fanfiction.net/s/123"}

        self.email_info.get_urls.side_effect = get_urls_then_shutdown

        email_watcher(
            self.email_info,
            self.notification_info,
            self.ingress_queue,
            self.url_parsers,
            self.active_urls,
            False,
            self.shutdown_event,
            self.recorder,
            self.config_store,
        )

        self.recorder.record_email_check.assert_called_once_with(
            urls_found=1,
            urls_new=0,
            urls_duplicate=0,
            urls_disabled_site=1,
            trigger="poll",
        )
        self.recorder.record_download_created.assert_not_called()

    @patch("services.url_ingester.regex_parsing.generate_FanficInfo_from_url")
    def test_counts_duplicates(self, mock_generate):
        """email_watcher tracks duplicate count in email check event."""
        from services.url_ingester import email_watcher

        url = "https://archiveofourown.org/works/123"
        fanfic = FanficInfo(url=url, site="ao3")
        mock_generate.return_value = fanfic
        self.active_urls[url] = {"site": "ao3"}  # Already active

        def get_urls_then_shutdown():
            self.shutdown_event.set()
            return {url}

        self.email_info.get_urls.side_effect = get_urls_then_shutdown

        email_watcher(
            self.email_info,
            self.notification_info,
            self.ingress_queue,
            self.url_parsers,
            self.active_urls,
            False,
            self.shutdown_event,
            self.recorder,
            self.config_store,
        )

        self.recorder.record_email_check.assert_called_once_with(
            urls_found=1,
            urls_new=0,
            urls_duplicate=1,
            urls_disabled_site=0,
            trigger="poll",
        )


class TestHandleFailureInstrumentation(unittest.TestCase):
    """Tests for handle_failure history recording."""

    def setUp(self):
        from models.context import WorkerContext

        self.fanfic = FanficInfo(url="https://ao3.org/works/1", site="ao3")
        self.notification_info = MagicMock()
        self.ingress_queue = MagicMock()
        self.waiting_queue = MagicMock()
        self.retry_config = RetryConfig()
        self.recorder = MagicMock()
        self.calibre_client = MagicMock()
        self.calibre_client.cdb_info = None
        self.ctx = WorkerContext(
            calibre_client=self.calibre_client,
            notification_info=self.notification_info,
            ingress_queue=self.ingress_queue,
            waiting_queue=self.waiting_queue,
            retry_config=self.retry_config,
            history_recorder=self.recorder,
            active_urls={},
        )

    def test_records_retry_event_on_retry(self):
        """handle_failure records a retry event when decision is RETRY."""
        from workers.handlers import handle_failure

        # First failure → RETRY
        handle_failure(self.fanfic, self.ctx)

        self.recorder.record_retry.assert_called_once()
        call_kwargs = self.recorder.record_retry.call_args
        self.assertEqual(call_kwargs.kwargs["url"], "https://ao3.org/works/1")
        self.assertEqual(call_kwargs.kwargs["action"], "retry")

    def test_records_error_message_on_retry(self):
        """handle_failure stores the detailed failure text on retry records."""
        from workers.handlers import handle_failure

        handle_failure(
            self.fanfic,
            self.ctx,
            error_message="calibredb: duplicate format",
        )

        self.assertEqual(
            self.recorder.record_retry.call_args.kwargs["error_message"],
            "calibredb: duplicate format",
        )
        self.assertEqual(
            self.recorder.record_download_waiting.call_args.kwargs["error_message"],
            "calibredb: duplicate format",
        )

    def test_records_abandon_event(self):
        """handle_failure records download_abandoned when retries exhausted."""
        from workers.handlers import handle_failure

        # Exhaust retries
        self.fanfic.repeats = self.retry_config.max_normal_retries + 1
        self.retry_config.hail_mary_enabled = False

        handle_failure(self.fanfic, self.ctx)

        self.recorder.record_download_abandoned.assert_called_once()
        self.recorder.record_retry.assert_not_called()

    def test_records_hail_mary_retry(self):
        """handle_failure records hail_mary retry event."""
        from workers.handlers import handle_failure

        # Set to one before hail mary threshold (increment_repeat adds 1)
        self.fanfic.repeats = self.retry_config.max_normal_retries - 1
        self.retry_config.hail_mary_enabled = True

        handle_failure(self.fanfic, self.ctx)

        self.recorder.record_retry.assert_called_once()
        call_kwargs = self.recorder.record_retry.call_args
        self.assertEqual(call_kwargs.kwargs["action"], "hail_mary")


class TestProcessFanficAdditionInstrumentation(unittest.TestCase):
    """Tests for process_fanfic_addition history recording."""

    def setUp(self):
        from models.context import WorkerContext

        self.fanfic = FanficInfo(
            url="https://ao3.org/works/1", site="ao3", title="Test Story"
        )
        self.fanfic.calibre_id = "42"
        self.calibre_client = MagicMock()
        self.calibre_client.cdb_info.metadata_preservation_mode = "remove_add"
        self.notification_info = MagicMock()
        self.ingress_queue = MagicMock()
        self.waiting_queue = MagicMock()
        self.retry_config = RetryConfig()
        self.recorder = MagicMock()
        self.ctx = WorkerContext(
            calibre_client=self.calibre_client,
            notification_info=self.notification_info,
            ingress_queue=self.ingress_queue,
            waiting_queue=self.waiting_queue,
            retry_config=self.retry_config,
            history_recorder=self.recorder,
            active_urls={},
        )

    @patch("workers.handlers.update_strategies")
    def test_records_success(self, mock_strategies):
        """process_fanfic_addition records download_success on success."""
        from workers.handlers import process_fanfic_addition

        mock_strategy = MagicMock()
        mock_strategy.execute.return_value = (True, None)
        mock_strategies.RemoveAddStrategy.return_value = mock_strategy

        process_fanfic_addition(
            self.fanfic,
            self.ctx,
            "/tmp/test",
            "test.epub",
        )

        self.recorder.record_download_success.assert_called_once_with(
            url="https://ao3.org/works/1",
            title="Test Story",
            calibre_id="42",
            site="ao3",
        )

    @patch("workers.handlers.update_strategies")
    def test_records_failure_on_exception(self, mock_strategies):
        """process_fanfic_addition records download_failed on exception."""
        from workers.handlers import process_fanfic_addition

        mock_strategies.RemoveAddStrategy.side_effect = Exception("Calibre failed")

        process_fanfic_addition(
            self.fanfic,
            self.ctx,
            "/tmp/test",
            "test.epub",
        )

        self.recorder.record_download_failed.assert_called_once_with(
            "https://ao3.org/works/1", "Calibre failed", site="ao3"
        )


class TestWaitProcessorInstrumentation(unittest.TestCase):
    """Tests for wait_processor history recording."""

    def test_records_retry_fired_when_item_expires(self):
        """wait_processor records retry_fired when heap item expires."""
        from services.ff_waiter import wait_processor

        fanfic = FanficInfo(url="https://ao3.org/works/1", site="ao3")
        fanfic.repeats = 3
        fanfic.retry_decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.RETRY,
            delay_minutes=0.0,  # Expire immediately
            should_notify=False,
            notification_message="",
        )

        ingress_queue = MagicMock()
        waiting_queue = MagicMock()
        shutdown_event = threading.Event()
        recorder = MagicMock()

        # First call returns the fanfic, second triggers shutdown
        call_count = [0]

        def queue_get_side_effect(timeout=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return fanfic
            # On second call, signal shutdown and raise Empty
            shutdown_event.set()
            raise Empty()

        waiting_queue.get.side_effect = queue_get_side_effect

        wait_processor(
            ingress_queue,
            waiting_queue,
            False,
            shutdown_event,
            recorder,
            {},
        )

        recorder.record_retry_fired.assert_called_once_with(
            "https://ao3.org/works/1", 3
        )


class TestNotificationWrapperInstrumentation(unittest.TestCase):
    """Tests for NotificationWrapper history recording."""

    @patch("notifications.notification_wrapper.AppriseNotification")
    def test_records_notification_event(self, mock_apprise_cls):
        """NotificationWrapper records notification after dispatch."""
        from notifications.notification_wrapper import NotificationWrapper

        mock_worker = MagicMock()
        mock_worker.is_enabled.return_value = True
        mock_worker.enabled = True
        mock_apprise_cls.return_value = mock_worker

        cfg = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path="/tmp/calibre"),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )
        recorder = MagicMock()
        wrapper = NotificationWrapper(cfg, MagicMock(), recorder)

        wrapper.send_notification("Title", "Body", "ao3")

        recorder.record_notification.assert_called_once_with("Title", "Body", "ao3")


if __name__ == "__main__":
    unittest.main()
