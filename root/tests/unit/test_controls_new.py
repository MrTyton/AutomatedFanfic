"""Unit tests for newly added control endpoints."""

from multiprocessing.synchronize import Event as MpEvent
from queue import Queue
import threading
from typing import cast
import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from models.active_urls import ActiveUrlsDict
from models.fanfic_info import FanficInfo
from models.queue_types import IngressQueue, WaitingQueue, WorkerQueues
from web.dependencies import WebState
from web.server import create_app


class TestNewControlsRoutes(unittest.TestCase):
    """Tests for the new control endpoints: toggle-coordinator, toggle-site, retry-all, cancel-all, clear-errors, restart-daemon."""

    def setUp(self) -> None:
        self.state = WebState()
        self.app = create_app(self.state)
        self.client = TestClient(self.app)

    def test_toggle_coordinator_success(self) -> None:
        status_dict: dict[str, object] = {"paused": False}
        self.state.coordinator_status = status_dict

        resp = self.client.post("/api/controls/toggle-coordinator")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["message"], "Coordinator paused")
        self.assertTrue(status_dict["paused"])

        resp2 = self.client.post("/api/controls/toggle-coordinator")
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertTrue(data2["ok"])
        self.assertEqual(data2["message"], "Coordinator resumed")
        self.assertFalse(status_dict["paused"])

    def test_toggle_coordinator_when_status_unavailable(self) -> None:
        self.state.coordinator_status = None
        resp = self.client.post("/api/controls/toggle-coordinator")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertIn("unavailable", data["message"].lower())

    def test_toggle_site_success(self) -> None:
        mock_config_store = MagicMock()
        mock_config = MagicMock()
        mock_config.email.disabled_sites = ["fanfiction.net"]
        mock_config_store.get_config.return_value = mock_config
        self.state.config_store = mock_config_store

        # Toggling "fanfiction.net" removes it
        resp = self.client.post(
            "/api/controls/toggle-site", json={"site": "fanfiction.net"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("enabled", data["message"])
        mock_config_store.set.assert_called_with("email", "disabled_sites", [])

        # Toggling "archiveofourown.org" adds it
        resp2 = self.client.post(
            "/api/controls/toggle-site", json={"site": "archiveofourown.org"}
        )
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertTrue(data2["ok"])
        self.assertIn("disabled", data2["message"])
        mock_config_store.set.assert_called_with(
            "email", "disabled_sites", ["fanfiction.net", "archiveofourown.org"]
        )

    def test_toggle_site_invalid(self) -> None:
        resp = self.client.post("/api/controls/toggle-site", json={"site": "   "})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertIn("invalid", data["message"].lower())

    def test_retry_all_requeues_waiting_urls(self) -> None:
        ingress: Queue[FanficInfo] = Queue()
        waiting: Queue[FanficInfo] = Queue()
        self.state.ingress_queue = cast(IngressQueue, ingress)
        self.state.waiting_queue = cast(WaitingQueue, waiting)
        self.state.active_urls = cast(
            ActiveUrlsDict,
            {
                "https://archiveofourown.org/works/1": {
                    "site": "archiveofourown.org",
                    "title": "Story One",
                    "status": "waiting",
                    "retry_count": 2,
                },
                "https://archiveofourown.org/works/2": {
                    "site": "archiveofourown.org",
                    "title": "Story Two",
                    "status": "processing",
                },
            },
        )

        resp = self.client.post("/api/controls/retry-all")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("Requeued 1", data["message"])
        self.assertEqual(ingress.qsize(), 1)
        item = ingress.get_nowait()
        self.assertIn("archiveofourown.org/works/1", item.url)

    def test_retry_all_when_none_waiting(self) -> None:
        ingress: Queue[FanficInfo] = Queue()
        self.state.ingress_queue = cast(IngressQueue, ingress)
        self.state.active_urls = cast(
            ActiveUrlsDict,
            {
                "https://archiveofourown.org/works/2": {
                    "site": "archiveofourown.org",
                    "status": "processing",
                },
            },
        )
        resp = self.client.post("/api/controls/retry-all")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["message"], "Requeued 0 waiting downloads")
        self.assertEqual(ingress.qsize(), 0)

    def test_cancel_all_in_flight(self) -> None:
        ingress: Queue[FanficInfo] = Queue()
        waiting: Queue[FanficInfo] = Queue()
        worker_q: Queue[FanficInfo] = Queue()
        worker_queues: dict[str, Queue[FanficInfo]] = {"archiveofourown.org": worker_q}
        self.state.ingress_queue = cast(IngressQueue, ingress)
        self.state.waiting_queue = cast(WaitingQueue, waiting)
        self.state.worker_queues = cast(WorkerQueues, worker_queues)

        fic1 = FanficInfo(
            url="https://archiveofourown.org/works/1", site="archiveofourown.org"
        )
        fic2 = FanficInfo(
            url="https://archiveofourown.org/works/2", site="archiveofourown.org"
        )
        ingress.put(fic1)
        worker_q.put(fic2)

        active = {
            fic1.url: {"site": "archiveofourown.org", "status": "queued"},
            fic2.url: {"site": "archiveofourown.org", "status": "processing"},
        }
        self.state.active_urls = cast(ActiveUrlsDict, active)

        resp = self.client.post("/api/controls/cancel-all")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(ingress.qsize(), 0)
        self.assertEqual(worker_q.qsize(), 0)
        self.assertEqual(active[fic1.url]["status"], "cancelled")
        self.assertEqual(active[fic2.url]["status"], "cancelled")

    def test_clear_errors(self) -> None:
        active = {
            "https://archiveofourown.org/works/1": {
                "site": "archiveofourown.org",
                "status": "failed",
                "error_message": "Network timeout",
            }
        }
        self.state.active_urls = cast(ActiveUrlsDict, active)

        # Clear specific URL
        resp = self.client.post(
            "/api/controls/clear-errors",
            json={"url": "https://archiveofourown.org/works/1"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(
            active["https://archiveofourown.org/works/1"].get("error_dismissed")
        )

        # Clear all errors
        resp2 = self.client.post("/api/controls/clear-errors", json={})
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.json()["ok"])

    def test_restart_daemon_web_server(self) -> None:
        restart_event = threading.Event()
        self.state.web_restart_event = cast(MpEvent, restart_event)

        resp = self.client.post(
            "/api/controls/restart-daemon", json={"name": "WebServer"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(restart_event.is_set())

    def test_restart_daemon_supervisor(self) -> None:
        sup_event = threading.Event()
        setattr(self.state, "supervisor_restart_event", sup_event)

        resp = self.client.post(
            "/api/controls/restart-daemon", json={"name": "Coordinator"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(sup_event.is_set())

    def test_restart_daemon_unknown(self) -> None:
        resp = self.client.post(
            "/api/controls/restart-daemon", json={"name": "NonExistentService"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertIn("unknown daemon", data["message"].lower())
