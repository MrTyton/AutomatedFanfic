"""Tests for WebSocket dashboard endpoint."""

import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from web.dependencies import WebState
from web.server import create_app


class TestWebSocketDashboard(unittest.TestCase):
    """Tests for /ws/dashboard WebSocket endpoint."""

    def setUp(self):
        self.state = WebState()
        self.app = create_app(self.state)
        self.client = TestClient(self.app)

    def test_websocket_connect_receive_snapshot(self):
        """Client connects and receives at least one snapshot."""
        with self.client.websocket_connect("/ws/dashboard") as ws:
            data = ws.receive_json()
            self.assertIn("timestamp", data)
            self.assertIn("active_downloads", data)
            self.assertIn("queued_downloads", data)
            self.assertIn("queues", data)
            self.assertIn("processes", data)
            self.assertIn("recent_downloads", data)
            self.assertIn("recent_activity", data)

    def test_snapshot_with_active_urls(self):
        """Snapshot separates queued (no status) vs processing (status=processing) URLs."""
        self.state.active_urls = {
            "https://ao3.org/works/1": {
                "site": "archiveofourown",
                "status": "processing",
            },
            "https://ao3.org/works/2": {"site": "archiveofourown", "status": "queued"},
        }
        with self.client.websocket_connect("/ws/dashboard") as ws:
            data = ws.receive_json()
            # Only status=processing appears in active_downloads
            self.assertEqual(data["active_downloads"]["count"], 1)
            active_urls = [item["url"] for item in data["active_downloads"]["items"]]
            self.assertIn("https://ao3.org/works/1", active_urls)
            # status=queued appears in queued_downloads
            self.assertEqual(data["queued_downloads"]["count"], 1)
            queued_urls = [item["url"] for item in data["queued_downloads"]["items"]]
            self.assertIn("https://ao3.org/works/2", queued_urls)

    def test_snapshot_with_queues(self):
        """Snapshot includes queue sizes when available."""
        mock_q = MagicMock()
        mock_q.qsize.return_value = 3
        self.state.ingress_queue = mock_q

        with self.client.websocket_connect("/ws/dashboard") as ws:
            data = ws.receive_json()
            self.assertEqual(data["queues"]["ingress"], 3)

    def test_snapshot_with_process_status(self):
        """Snapshot includes process info when callable is provided."""
        self.state.process_status_callable = lambda: {"supervisor": "running"}
        with self.client.websocket_connect("/ws/dashboard") as ws:
            data = ws.receive_json()
            self.assertIn("supervisor", data["processes"])

    def test_snapshot_includes_waiting_error_details(self):
        """Waiting rows include history metadata needed by dashboard actions."""

        class StubHistoryDB:
            async def get_waiting_urls(self):
                return [
                    {
                        "url": "https://ao3.org/works/1",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                        "site": "ao3",
                        "title": "Story One",
                        "calibre_id": "42",
                        "error_message": "calibredb stderr",
                    }
                ]

            async def get_recent_downloads(self, limit=20):
                return []

            async def get_recent_activity(self, limit=20):
                return []

        self.state.active_urls = {
            "https://ao3.org/works/1": {"site": "ao3", "title": "Story One", "status": "waiting"}
        }
        self.state.history_db = StubHistoryDB()

        with self.client.websocket_connect("/ws/dashboard") as ws:
            data = ws.receive_json()
            self.assertEqual(data["waiting_downloads"]["count"], 1)
            waiting = data["waiting_downloads"]["items"][0]
            self.assertEqual(waiting["calibre_id"], "42")
            self.assertEqual(waiting["error_message"], "calibredb stderr")

    def test_snapshot_empty_state(self):
        """Snapshot handles completely empty state gracefully."""
        with self.client.websocket_connect("/ws/dashboard") as ws:
            data = ws.receive_json()
            self.assertEqual(data["active_downloads"]["count"], 0)
            self.assertEqual(data["queues"], {})
            self.assertEqual(data["processes"], {})
            self.assertEqual(data["recent_downloads"], [])
            self.assertEqual(data["recent_activity"], [])
