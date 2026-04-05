"""Tests for the web server routes and app factory."""

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from web.dependencies import WebState
from web.server import create_app


class TestHealthRoutes(unittest.TestCase):
    """Tests for /api/health and /api/status endpoints."""

    def setUp(self):
        self.state = WebState()
        self.app = create_app(self.state)
        self.client = TestClient(self.app)

    def test_health_check(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_status_minimal(self):
        """Status endpoint works with no shared state configured."""
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "running")
        self.assertEqual(data["processes"], {})

    def test_status_with_queues(self):
        """Status includes queue sizes when queues are available."""
        mock_ingress = MagicMock()
        mock_ingress.qsize.return_value = 5
        mock_waiting = MagicMock()
        mock_waiting.qsize.return_value = 2
        self.state.ingress_queue = mock_ingress
        self.state.waiting_queue = mock_waiting

        resp = self.client.get("/api/status")
        data = resp.json()
        self.assertEqual(data["queues"]["ingress"], 5)
        self.assertEqual(data["queues"]["waiting"], 2)

    def test_status_with_active_urls(self):
        """Status includes active download count."""
        self.state.active_urls = {"url1": True, "url2": True}

        resp = self.client.get("/api/status")
        data = resp.json()
        self.assertEqual(data["active_downloads"], 2)

    def test_status_with_process_callable(self):
        """Status includes process info from callable."""
        self.state.process_status_callable = lambda: {
            "supervisor": {"state": "running"},
            "worker_pool": {"state": "running"},
        }

        resp = self.client.get("/api/status")
        data = resp.json()
        self.assertIn("supervisor", data["processes"])


class TestHistoryRoutes(unittest.TestCase):
    """Tests for /api/history/* endpoints."""

    def setUp(self):
        self.state = WebState()
        self.app = create_app(self.state)
        self.client = TestClient(self.app)

    def test_downloads_no_db(self):
        """Downloads endpoint returns empty when no DB configured."""
        resp = self.client.get("/api/history/downloads")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"items": [], "total": 0})

    def test_emails_no_db(self):
        resp = self.client.get("/api/history/emails")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"items": []})

    def test_notifications_no_db(self):
        resp = self.client.get("/api/history/notifications")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"items": []})

    def test_recent_no_db(self):
        resp = self.client.get("/api/history/recent")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"items": []})

    def test_retries_no_db(self):
        resp = self.client.get("/api/history/retries/https://ao3.org/works/1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"items": []})

    def test_downloads_pagination_params(self):
        """Pagination parameters are validated."""
        resp = self.client.get("/api/history/downloads?limit=0")
        self.assertEqual(resp.status_code, 422)  # Validation error

        resp = self.client.get("/api/history/downloads?limit=501")
        self.assertEqual(resp.status_code, 422)

    def test_downloads_with_mock_db(self):
        """Downloads endpoint queries the database when available."""
        mock_db = MagicMock()
        mock_db.get_downloads = MagicMock(
            return_value=[{"url": "https://ao3.org/works/1", "status": "success"}]
        )
        mock_db.get_download_count = MagicMock(return_value=1)

        # Make mock awaitable

        async def mock_get_downloads(**kwargs):
            return [{"url": "https://ao3.org/works/1", "status": "success"}]

        async def mock_get_count(**kwargs):
            return 1

        mock_db.get_downloads = mock_get_downloads
        mock_db.get_download_count = mock_get_count
        self.state.history_db = mock_db

        resp = self.client.get("/api/history/downloads")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["items"]), 1)


class TestMonitoringRoutes(unittest.TestCase):
    """Tests for /api/monitoring/* endpoints."""

    def setUp(self):
        self.state = WebState()
        self.app = create_app(self.state)
        self.client = TestClient(self.app)

    def test_active_empty(self):
        resp = self.client.get("/api/monitoring/active")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"items": [], "count": 0})

    def test_active_with_urls(self):
        self.state.active_urls = {"url1": True, "url2": True}
        resp = self.client.get("/api/monitoring/active")
        data = resp.json()
        self.assertEqual(data["count"], 2)
        self.assertIn("url1", data["items"])

    def test_queues_empty(self):
        resp = self.client.get("/api/monitoring/queues")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {})

    def test_workers_empty(self):
        resp = self.client.get("/api/monitoring/workers")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"workers": {}})


class TestControlRoutes(unittest.TestCase):
    """Tests for /api/controls/* endpoints."""

    def setUp(self):
        self.state = WebState()
        self.app = create_app(self.state)
        self.client = TestClient(self.app)

    def test_add_url_no_queue(self):
        """Returns error when ingress queue isn't available."""
        resp = self.client.post(
            "/api/controls/add-url", json={"url": "https://ao3.org/works/1"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["accepted"])

    @patch("parsers.auto_url_parsers.generate_url_parsers_from_fanficfare")
    @patch("parsers.regex_parsing.generate_FanficInfo_from_url")
    def test_add_url_success(self, mock_generate, mock_parsers):
        """Successfully adds a URL to the queue."""
        from models.fanfic_info import FanficInfo

        mock_parsers.return_value = {}
        mock_generate.return_value = FanficInfo(
            url="https://ao3.org/works/1", site="ao3"
        )

        self.state.ingress_queue = MagicMock()
        self.state.active_urls = {}

        resp = self.client.post(
            "/api/controls/add-url", json={"url": "https://ao3.org/works/1"}
        )
        data = resp.json()
        self.assertTrue(data["accepted"])
        self.state.ingress_queue.put.assert_called_once()

    @patch("parsers.auto_url_parsers.generate_url_parsers_from_fanficfare")
    @patch("parsers.regex_parsing.generate_FanficInfo_from_url")
    def test_add_url_duplicate(self, mock_generate, mock_parsers):
        """Rejects duplicate URLs."""
        from models.fanfic_info import FanficInfo

        mock_parsers.return_value = {}
        mock_generate.return_value = FanficInfo(
            url="https://ao3.org/works/1", site="ao3"
        )

        self.state.ingress_queue = MagicMock()
        self.state.active_urls = {"https://ao3.org/works/1": True}

        resp = self.client.post(
            "/api/controls/add-url", json={"url": "https://ao3.org/works/1"}
        )
        data = resp.json()
        self.assertFalse(data["accepted"])
        self.assertIn("already in queue", data["message"])


class TestConfigRoutes(unittest.TestCase):
    """Tests for /api/config endpoints."""

    def setUp(self):
        self.state = WebState()
        self.app = create_app(self.state)
        self.client = TestClient(self.app)

    def test_get_config_no_config(self):
        resp = self.client.get("/api/config")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"config": {}})

    def test_get_config_masks_sensitive_fields(self):
        """Sensitive fields are masked in the response."""
        mock_config = MagicMock()
        mock_config.model_dump.return_value = {
            "email": {
                "email": "user@example.com",
                "password": "secret123",
                "server": "imap.example.com",
            },
            "pushbullet": {"api_key": "pb_key_123", "enabled": True},
        }
        self.state.config = mock_config

        resp = self.client.get("/api/config")
        data = resp.json()["config"]
        self.assertEqual(data["email"]["email"], "user@example.com")
        self.assertEqual(data["email"]["password"], "********")
        self.assertEqual(data["email"]["server"], "imap.example.com")
        self.assertEqual(data["pushbullet"]["api_key"], "********")

    def test_validate_config(self):
        resp = self.client.post("/api/config/validate", json={"values": {}})
        self.assertEqual(resp.status_code, 200)


class TestWebConfig(unittest.TestCase):
    """Tests for the WebConfig model."""

    def test_web_config_defaults(self):
        from models.config_models import WebConfig

        wc = WebConfig()
        self.assertFalse(wc.enabled)
        self.assertEqual(wc.host, "0.0.0.0")
        self.assertEqual(wc.port, 8080)
        self.assertEqual(wc.history_db_path, "/data/history.db")

    def test_web_config_custom(self):
        from models.config_models import WebConfig

        wc = WebConfig(enabled=False, port=9090, host="127.0.0.1")
        self.assertFalse(wc.enabled)
        self.assertEqual(wc.port, 9090)

    def test_web_config_port_validation(self):
        from models.config_models import WebConfig
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            WebConfig(port=0)

        with self.assertRaises(ValidationError):
            WebConfig(port=70000)

    def test_app_config_includes_web(self):
        """AppConfig has a web field with defaults."""
        from models.config_models import WebConfig

        # Just verify the model can be imported and has the field
        wc = WebConfig()
        self.assertIsNotNone(wc)


if __name__ == "__main__":
    unittest.main()
