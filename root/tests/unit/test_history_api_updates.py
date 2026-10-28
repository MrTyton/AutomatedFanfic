"""Unit tests for history database pagination counts and retries filtering."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from history.database import AsyncHistoryDB
from web.dependencies import WebState
from web.server import create_app


class TestHistoryApiUpdates(unittest.TestCase):
    """Tests for history API returning total counts and supporting filters."""

    def setUp(self) -> None:
        self.mock_db = MagicMock(spec=AsyncHistoryDB)
        self.state = WebState(history_db=self.mock_db)
        self.app = create_app(self.state)
        self.client = TestClient(self.app)

    def test_list_emails_returns_total(self) -> None:
        self.mock_db.get_email_checks = AsyncMock(
            return_value=[
                {"id": 1, "checked_at": "2026-10-28 12:00:00", "urls_found": 2}
            ]
        )
        self.mock_db.get_email_checks_count = AsyncMock(return_value=42)

        resp = self.client.get("/api/history/emails?limit=10&offset=0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["total"], 42)
        self.mock_db.get_email_checks.assert_awaited_once_with(limit=10, offset=0)
        self.mock_db.get_email_checks_count.assert_awaited_once()

    def test_list_notifications_returns_total(self) -> None:
        self.mock_db.get_notifications = AsyncMock(
            return_value=[{"id": 1, "title": "Alert", "body": "Success"}]
        )
        self.mock_db.get_notifications_count = AsyncMock(return_value=15)

        resp = self.client.get("/api/history/notifications?limit=10&offset=0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["total"], 15)
        self.mock_db.get_notifications.assert_awaited_once_with(limit=10, offset=0)
        self.mock_db.get_notifications_count.assert_awaited_once()

    def test_list_retries_with_site_and_search_filters(self) -> None:
        self.mock_db.get_retries = AsyncMock(
            return_value=[
                {"id": 1, "url": "https://archiveofourown.org/works/1", "site": "ao3"}
            ]
        )
        self.mock_db.get_retry_count = AsyncMock(return_value=1)

        resp = self.client.get(
            "/api/history/retries?page=1&page_size=25&site=ao3&search=works/1"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["total"], 1)
        self.mock_db.get_retries.assert_awaited_once_with(
            site="ao3", search="works/1", limit=25, offset=0
        )
        self.mock_db.get_retry_count.assert_awaited_once_with(
            site="ao3", search="works/1"
        )
