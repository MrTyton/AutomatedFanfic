"""Unit tests for enriched websocket dashboard snapshot."""

import asyncio
from typing import cast
import unittest
from unittest.mock import AsyncMock, MagicMock

from models.active_urls import ActiveUrlsDict
from models.config_models import AppConfig, CalibreConfig, EmailConfig, RetryConfig
from web.dependencies import WebState
from web.routes.websocket import _build_snapshot


class TestWebsocketSnapshot(unittest.TestCase):
    """Tests that _build_snapshot produces all expected enriched fields."""

    async def _async_test_snapshot(self) -> None:
        mock_db = MagicMock()
        mock_db.get_waiting_urls = AsyncMock(return_value=[])
        mock_db.get_recent_downloads = AsyncMock(return_value=[])
        mock_db.get_recent_activity = AsyncMock(return_value=[])
        mock_db.get_email_checks = AsyncMock(
            return_value=[
                {"id": 1, "checked_at": "2026-10-28 12:00:00", "urls_found": 3}
            ]
        )

        cfg = AppConfig(
            email=EmailConfig(
                email="user@test.com",
                password="pw",
                server="imap.test.com",
                disabled_sites=["wattpad.com"],
            ),
            calibre=CalibreConfig(path="http://calibre.local:8080/#Library"),
            retry=RetryConfig(max_normal_retries=7),
        )

        state = WebState(
            history_db=mock_db,
            config=cfg,
            active_urls=cast(
                ActiveUrlsDict,
                {
                    "https://archiveofourown.org/works/1": {
                        "site": "archiveofourown.org",
                        "status": "processing",
                    }
                },
            ),
            coordinator_status={"paused": True},
        )

        snap = await _build_snapshot(state)

        # Enriched fields check
        self.assertTrue(snap.get("coordinator_paused"))
        self.assertEqual(snap.get("disabled_sites"), ["wattpad.com"])
        self.assertEqual(snap.get("max_normal_retries"), 7)
        self.assertEqual(
            snap.get("calibre_server_url"), "http://calibre.local:8080/#Library"
        )
        self.assertIsNotNone(snap.get("daemon_details"))
        daemon_details = snap.get("daemon_details")
        self.assertIsInstance(daemon_details, dict)
        assert isinstance(daemon_details, dict)
        self.assertIn("Coordinator", daemon_details)
        coord_info = daemon_details["Coordinator"]
        assert isinstance(coord_info, dict)
        self.assertEqual(coord_info["status"], "paused")

        self.assertIsNotNone(snap.get("site_worker_stats"))
        worker_stats = snap.get("site_worker_stats")
        self.assertIsInstance(worker_stats, dict)
        assert isinstance(worker_stats, dict)
        self.assertIn("catalog_sites", worker_stats)
        self.assertIn("notable_sites", worker_stats)
        self.assertEqual(snap.get("dismissed_error_urls"), [])

        # Review Focus 5: empty/uninitialized WebState must not raise exceptions
        empty_state = WebState()
        empty_snap = await _build_snapshot(empty_state)
        self.assertFalse(empty_snap.get("coordinator_paused"))
        self.assertEqual(empty_snap.get("disabled_sites"), [])
        self.assertIsNone(empty_snap.get("calibre_server_url"))

    def test_snapshot_sync_runner(self) -> None:
        asyncio.run(self._async_test_snapshot())
