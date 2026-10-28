"""Unit tests for coordinator pause behavior and backlog/heap drainage on shutdown."""

from collections import deque
from queue import Queue
import threading
import time
from typing import cast
import unittest
from unittest.mock import MagicMock

from models.active_urls import ActiveUrlsDict
from models.fanfic_info import FanficInfo
from models.queue_types import (
    IngressItem,
    IngressQueue,
    ShutdownEvent,
    WaitingQueue,
    WorkerQueue,
    WorkerQueues,
)
from models.retry_types import FailureAction, RetryDecision
from services.coordinator import Coordinator
from services.ff_waiter import wait_processor


class TestCoordinatorPauseAndDrain(unittest.TestCase):
    """Tests for coordinator pause flag and state preservation on shutdown."""

    def test_coordinator_paused_stops_task_assignment(self) -> None:
        ingress: Queue[IngressItem] = Queue()
        worker_q: Queue[FanficInfo | None] = Queue()
        worker_queues = {"ao3-worker": cast(WorkerQueue, worker_q)}
        active_urls: dict[str, dict[str, object]] = {}
        status_dict: dict[str, object] = {"paused": True}

        coord = Coordinator(
            ingress_queue=cast(IngressQueue, ingress),
            worker_queues=cast(WorkerQueues, worker_queues),
            verbose=False,
            shutdown_event=threading.Event(),
            active_urls=cast(ActiveUrlsDict, active_urls),
            history_recorder=MagicMock(),
            url_parsers={},
            config_store=MagicMock(),
            scale_queue=MagicMock(),
            coordinator_status=status_dict,
        )

        fic = FanficInfo(url="https://archiveofourown.org/works/1", site="ao3")
        coord.state.backlog["ao3"] = deque([fic])
        coord.state.idle_workers.add("ao3-worker")

        # When paused, _assign_work_if_possible should NOT dispatch
        coord._assign_work_if_possible()
        self.assertEqual(worker_q.qsize(), 0)
        self.assertEqual(len(coord.state.backlog["ao3"]), 1)
        self.assertIn("ao3-worker", coord.state.idle_workers)

        # When unpaused, it should dispatch
        status_dict["paused"] = False
        coord._assign_work_if_possible()
        self.assertEqual(worker_q.qsize(), 1)
        self.assertEqual(len(coord.state.backlog["ao3"]), 0)

    def test_coordinator_shutdown_drains_backlog_to_ingress(self) -> None:
        ingress: Queue[IngressItem] = Queue()
        worker_queues: dict[str, WorkerQueue] = {}
        active_urls: dict[str, dict[str, object]] = {}

        coord = Coordinator(
            ingress_queue=cast(IngressQueue, ingress),
            worker_queues=cast(WorkerQueues, worker_queues),
            verbose=False,
            shutdown_event=threading.Event(),
            active_urls=cast(ActiveUrlsDict, active_urls),
            history_recorder=MagicMock(),
            url_parsers={},
            config_store=MagicMock(),
            scale_queue=MagicMock(),
            coordinator_status={},
        )

        fic1 = FanficInfo(url="https://archiveofourown.org/works/1", site="ao3")
        fic2 = FanficInfo(url="https://archiveofourown.org/works/2", site="ffnet")
        coord.state.backlog["ao3"] = deque([fic1])
        coord.state.backlog["ffnet"] = deque([fic2])

        coord._log_and_drain_backlog_on_shutdown()

        self.assertEqual(ingress.qsize(), 2)
        drained_urls = {cast(FanficInfo, ingress.get_nowait()).url for _ in range(2)}
        self.assertEqual(
            drained_urls,
            {
                "https://archiveofourown.org/works/1",
                "https://archiveofourown.org/works/2",
            },
        )
        self.assertEqual(len(coord.state.backlog["ao3"]), 0)
        self.assertEqual(len(coord.state.backlog["ffnet"]), 0)

    def test_waiter_shutdown_drains_heap_to_waiting_queue(self) -> None:
        ingress: Queue[IngressItem] = Queue()
        waiting: Queue[FanficInfo | None] = Queue()
        shutdown_event = threading.Event()
        active_urls: dict[str, dict[str, object]] = {}

        fic = FanficInfo(url="https://archiveofourown.org/works/1", site="ao3")
        fic.retry_decision = RetryDecision(
            action=FailureAction.RETRY, delay_minutes=10.0
        )
        waiting.put(fic)

        # Run wait_processor briefly in thread then trigger shutdown
        t = threading.Thread(
            target=wait_processor,
            args=(
                cast(IngressQueue, ingress),
                cast(WaitingQueue, waiting),
                False,
                cast(ShutdownEvent, shutdown_event),
                MagicMock(),
                cast(ActiveUrlsDict, active_urls),
            ),
        )
        t.start()
        # Wait until fic is consumed from waiting_queue and placed on heap
        time.sleep(0.1)
        shutdown_event.set()
        t.join(timeout=3.0)

        # The item should have been drained back onto waiting_queue on shutdown!
        self.assertFalse(t.is_alive())
        self.assertEqual(waiting.qsize(), 1)
        restored_item = waiting.get_nowait()
        self.assertIsInstance(restored_item, FanficInfo)
        assert restored_item is not None
        self.assertEqual(restored_item.url, fic.url)
