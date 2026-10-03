"""Tests for WebSocket dashboard endpoint."""

import asyncio
import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import web.routes.websocket as ws_module
from web.dependencies import WebState
from web.server import create_app


class TestWebSocketDashboard(unittest.TestCase):
    """Tests for /ws/dashboard WebSocket endpoint."""

    def setUp(self):
        self.state = WebState()
        self.app = create_app(self.state)
        self.client = TestClient(self.app)
        # Reset shared module state between tests to prevent leakage
        ws_module._latest_snapshot = None
        ws_module._bg_task = None
        ws_module._history_cache = {
            "recent_downloads": [],
            "recent_activity": [],
            "expires_at": 0.0,
        }

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
            "https://ao3.org/works/1": {
                "site": "ao3",
                "title": "Story One",
                "status": "waiting",
            }
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

    def test_broadcast_throttle_drops_rapid_calls(self):
        """broadcast() should silently drop a second call within 100 ms."""
        import asyncio
        import json
        import web.routes.websocket as ws_module
        from web.routes.websocket import broadcast, _connections

        # Reset module state
        ws_module._last_broadcast_time = 0.0

        sent_payloads = []

        class FakeWS:
            client_state = None

            async def send_text(self, data):
                sent_payloads.append(data)

        fake = FakeWS()
        _connections.add(fake)
        try:

            async def run():
                await broadcast({"event": "first"})
                # Immediately call again — should be throttled (no sleep between calls)
                await broadcast({"event": "second"})

            asyncio.run(run())
            # Only the first message should have been delivered
            self.assertEqual(len(sent_payloads), 1)
            self.assertEqual(json.loads(sent_payloads[0])["event"], "first")
        finally:
            _connections.discard(fake)
            ws_module._last_broadcast_time = 0.0

    def test_broadcast_allows_call_after_interval(self):
        """broadcast() should allow a call when last broadcast was 200+ ms ago."""
        import asyncio
        import time
        import web.routes.websocket as ws_module
        from web.routes.websocket import broadcast, _connections

        # Pretend last broadcast was 200 ms ago (past the 100 ms window)
        ws_module._last_broadcast_time = time.time() - 0.2

        sent_payloads = []

        class FakeWS:
            client_state = None

            async def send_text(self, data):
                sent_payloads.append(data)

        fake = FakeWS()
        _connections.add(fake)
        try:
            asyncio.run(broadcast({"event": "ok"}))
            self.assertEqual(len(sent_payloads), 1)
        finally:
            _connections.discard(fake)
            ws_module._last_broadcast_time = 0.0

    def test_history_cache_avoids_repeat_queries(self):
        """_build_snapshot should only refresh history queries when TTL expires."""
        from web.routes.websocket import _build_snapshot

        call_counts = {"downloads": 0, "activity": 0}

        class StubHistoryDB:
            async def get_waiting_urls(self):
                return []

            async def get_recent_downloads(self, limit=20):
                call_counts["downloads"] += 1
                return [{"id": 1}]

            async def get_recent_activity(self, limit=20):
                call_counts["activity"] += 1
                return [{"id": 2}]

        self.state.history_db = StubHistoryDB()
        # Ensure cache is cold (expires_at=0.0 set in setUp)

        async def run():
            await _build_snapshot(self.state)  # cold cache → queries run
            await _build_snapshot(self.state)  # hot cache → queries skipped

        asyncio.run(run())
        # Each history query should have been called exactly once despite two builds
        self.assertEqual(
            call_counts["downloads"],
            1,
            "get_recent_downloads called more than once within TTL",
        )
        self.assertEqual(
            call_counts["activity"],
            1,
            "get_recent_activity called more than once within TTL",
        )

    def test_build_and_push_snapshot_sends_to_all_clients(self):
        """_build_and_push_snapshot should push identical snapshot to every connection."""
        from web.routes.websocket import _build_and_push_snapshot, _connections

        sent: dict[int, list] = {1: [], 2: []}

        class FakeWS:
            def __init__(self, n: int) -> None:
                self.n = n

            async def send_json(self, data: dict) -> None:
                sent[self.n].append(data)

        fake1, fake2 = FakeWS(1), FakeWS(2)
        _connections.add(fake1)
        _connections.add(fake2)
        try:
            asyncio.run(_build_and_push_snapshot(self.state))
            # Both clients should have received exactly one snapshot
            self.assertEqual(len(sent[1]), 1)
            self.assertEqual(len(sent[2]), 1)
            # Snapshots must be identical (same object built once)
            self.assertEqual(sent[1][0]["timestamp"], sent[2][0]["timestamp"])
            self.assertIn("active_downloads", sent[1][0])
        finally:
            _connections.discard(fake1)
            _connections.discard(fake2)
            ws_module._latest_snapshot = None

    def test_build_and_push_snapshot_removes_dead_connections(self):
        """_build_and_push_snapshot should drop connections that raise on send."""
        from web.routes.websocket import _build_and_push_snapshot, _connections

        class DeadWS:
            async def send_json(self, data: dict) -> None:
                raise RuntimeError("connection closed")

        dead = DeadWS()
        _connections.add(dead)
        try:
            asyncio.run(_build_and_push_snapshot(self.state))
            # Dead connection should have been removed
            self.assertNotIn(dead, _connections)
        finally:
            _connections.discard(dead)
            ws_module._latest_snapshot = None
