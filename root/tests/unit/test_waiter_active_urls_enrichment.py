import queue
import threading
import time
import unittest
from unittest.mock import MagicMock

from models import active_urls as active_urls_utils
from models.fanfic_info import FanficInfo
from models.retry_types import FailureAction, RetryDecision
from services import ff_waiter


class TestWaiterActiveUrlsEnrichment(unittest.TestCase):
    def test_mark_url_waiting_accepts_enriched_metadata(self):
        active_urls = {}
        url = "https://example.com/story/1"
        now = time.time()
        wait_until = now + 300.0
        delay_seconds = 300.0
        retry_count = 3

        result = active_urls_utils.mark_url_waiting(
            active_urls,
            url,
            site="example",
            title="Sample Story",
            calibre_id="42",
            wait_until=wait_until,
            delay_seconds=delay_seconds,
            retry_count=retry_count,
        )

        self.assertTrue(result)
        self.assertEqual(active_urls[url]["status"], "waiting")
        self.assertEqual(active_urls[url]["site"], "example")
        self.assertEqual(active_urls[url]["title"], "Sample Story")
        self.assertEqual(active_urls[url]["calibre_id"], "42")
        self.assertEqual(active_urls[url]["wait_until"], wait_until)
        self.assertEqual(active_urls[url]["delay_seconds"], delay_seconds)
        self.assertEqual(active_urls[url]["retry_count"], retry_count)

    def test_wait_processor_enriches_active_urls_with_wait_until_and_retry_count(self):
        waiting_q = queue.Queue()
        ingress_q = queue.Queue()
        active_urls = {}
        shutdown_event = threading.Event()
        history_recorder = MagicMock()

        fic = FanficInfo(
            url="https://archiveofourown.org/works/999",
            site="archiveofourown",
            repeats=2,
            retry_decision=RetryDecision(
                action=FailureAction.RETRY,
                delay_minutes=5.0,
                should_notify=False,
                notification_message="",
            ),
        )
        waiting_q.put(fic)
        waiting_q.put(None)  # Poison pill

        start_time = time.time()
        ff_waiter.wait_processor(
            ingress_queue=ingress_q,
            waiting_queue=waiting_q,
            verbose=False,
            shutdown_event=shutdown_event,
            history_recorder=history_recorder,
            active_urls=active_urls,
        )

        entry = active_urls.get(fic.url)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["status"], "waiting")
        self.assertEqual(entry["delay_seconds"], 300.0)
        self.assertEqual(entry["retry_count"], 2)
        self.assertGreaterEqual(entry["wait_until"], start_time + 299.0)
