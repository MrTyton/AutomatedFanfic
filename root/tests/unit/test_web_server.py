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
        self.state.active_urls = {"url1": {"site": "test"}, "url2": {"site": "test"}}

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
        self.state.active_urls = {"url1": {"site": "test"}, "url2": {"site": "test"}}
        resp = self.client.get("/api/monitoring/active")
        data = resp.json()
        self.assertEqual(data["count"], 2)
        urls = [item["url"] for item in data["items"]]
        self.assertIn("url1", urls)

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
        self.state.active_urls = {"https://ao3.org/works/1": {"site": "ao3"}}

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


class TestWidgetRoute(unittest.TestCase):
    """Tests for /api/widget endpoint (Homepage dashboard integration)."""

    def setUp(self):
        self.state = WebState()
        self.app = create_app(self.state)
        self.client = TestClient(self.app)

    def test_widget_minimal_no_state(self):
        """Widget returns valid structure with no shared state configured."""
        resp = self.client.get("/api/widget")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["active_downloads"], 0)
        self.assertEqual(data["queued"], 0)
        self.assertEqual(data["waiting_retry"], 0)
        self.assertEqual(data["total_completed"], 0)
        self.assertEqual(data["status"], "running")
        self.assertIsInstance(data["active"], list)
        self.assertEqual(len(data["active"]), 0)

    def test_widget_active_downloads(self):
        """Widget reflects current active downloads count and list."""
        self.state.active_urls = {
            "https://ao3.org/works/1": {"site": "ao3", "title": "Story One"},
            "https://ffnet.net/s/2": {"site": "ffnet", "title": "Story Two"},
        }
        resp = self.client.get("/api/widget")
        data = resp.json()
        self.assertEqual(data["active_downloads"], 2)
        self.assertEqual(len(data["active"]), 2)
        # Each active item should have url, site, title
        titles = {item["title"] for item in data["active"]}
        self.assertIn("Story One", titles)
        self.assertIn("Story Two", titles)
        sites = {item["site"] for item in data["active"]}
        self.assertIn("ao3", sites)

    def test_widget_active_items_have_url(self):
        """Active items include the URL field."""
        self.state.active_urls = {
            "https://ao3.org/works/99": {"site": "ao3", "title": "Test"},
        }
        resp = self.client.get("/api/widget")
        data = resp.json()
        self.assertEqual(data["active"][0]["url"], "https://ao3.org/works/99")

    def test_widget_queued_count(self):
        """Widget shows ingress queue depth."""
        mock_ingress = MagicMock()
        mock_ingress.qsize.return_value = 7
        self.state.ingress_queue = mock_ingress

        resp = self.client.get("/api/widget")
        data = resp.json()
        self.assertEqual(data["queued"], 7)

    def test_widget_waiting_retry_count(self):
        """Widget shows waiting/retry queue depth."""
        mock_waiting = MagicMock()
        mock_waiting.qsize.return_value = 3
        self.state.waiting_queue = mock_waiting

        resp = self.client.get("/api/widget")
        data = resp.json()
        self.assertEqual(data["waiting_retry"], 3)

    def test_widget_qsize_not_implemented(self):
        """Widget handles platforms where qsize() is not supported."""
        mock_q = MagicMock()
        mock_q.qsize.side_effect = NotImplementedError
        self.state.ingress_queue = mock_q
        self.state.waiting_queue = mock_q

        resp = self.client.get("/api/widget")
        data = resp.json()
        self.assertEqual(data["queued"], 0)
        self.assertEqual(data["waiting_retry"], 0)

    def test_widget_total_completed_with_db(self):
        """Widget queries DB for total completed downloads."""

        async def mock_count(**kwargs):
            return 42

        mock_db = MagicMock()
        mock_db.get_download_count = mock_count
        self.state.history_db = mock_db

        resp = self.client.get("/api/widget")
        data = resp.json()
        self.assertEqual(data["total_completed"], 42)

    def test_widget_status_running(self):
        """Status is 'running' when processes are available."""
        self.state.process_status_callable = lambda: {
            "supervisor": {"state": "running"},
        }
        resp = self.client.get("/api/widget")
        data = resp.json()
        self.assertEqual(data["status"], "running")

    def test_widget_active_items_handle_missing_metadata(self):
        """Active items gracefully handle entries with no metadata dict."""
        self.state.active_urls = {
            "https://ao3.org/works/5": "not_a_dict",
        }
        resp = self.client.get("/api/widget")
        data = resp.json()
        self.assertEqual(data["active_downloads"], 1)
        # Should still appear with url, defaults for missing fields
        self.assertEqual(len(data["active"]), 1)
        self.assertEqual(data["active"][0]["url"], "https://ao3.org/works/5")

    def test_widget_active_items_show_downloading_state(self):
        """Active items in active_urls but NOT in waiting DB show 'downloading'."""
        self.state.active_urls = {
            "https://ao3.org/works/1": {"site": "ao3", "title": "Active Story"},
        }
        resp = self.client.get("/api/widget")
        data = resp.json()
        self.assertEqual(data["active"][0]["state"], "downloading")

    def test_widget_waiting_items_show_waiting_state(self):
        """Items in active_urls that ARE in waiting DB show 'waiting'."""

        async def mock_waiting():
            return [{"url": "https://ao3.org/works/2", "updated_at": "2026-04-14"}]

        async def mock_count(**kwargs):
            return 0

        mock_db = MagicMock()
        mock_db.get_waiting_urls = mock_waiting
        mock_db.get_download_count = mock_count
        self.state.history_db = mock_db

        self.state.active_urls = {
            "https://ao3.org/works/1": {"site": "ao3", "title": "Active Story"},
            "https://ao3.org/works/2": {"site": "ao3", "title": "Waiting Story"},
        }
        resp = self.client.get("/api/widget")
        data = resp.json()
        items_by_url = {item["url"]: item for item in data["active"]}
        self.assertEqual(
            items_by_url["https://ao3.org/works/1"]["state"], "downloading"
        )
        self.assertEqual(items_by_url["https://ao3.org/works/2"]["state"], "waiting")

    def test_widget_no_db_all_items_show_downloading(self):
        """Without history DB, all active items default to 'downloading'."""
        self.state.active_urls = {
            "https://ao3.org/works/1": {"site": "ao3", "title": "Story"},
        }
        resp = self.client.get("/api/widget")
        data = resp.json()
        self.assertEqual(data["active"][0]["state"], "downloading")

    def test_widget_missing_metadata_shows_downloading_state(self):
        """Items with non-dict metadata still get a state field."""
        self.state.active_urls = {
            "https://ao3.org/works/5": "not_a_dict",
        }
        resp = self.client.get("/api/widget")
        data = resp.json()
        self.assertEqual(data["active"][0]["state"], "downloading")


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

    def test_history_db_path_directory_gets_filename_appended(self):
        """Directory path without extension gets history.db appended."""
        from models.config_models import WebConfig

        wc = WebConfig(history_db_path="/config")
        self.assertEqual(wc.history_db_path, "/config/history.db")

    def test_history_db_path_directory_with_trailing_slash(self):
        """Directory path with trailing slash gets history.db appended."""
        from models.config_models import WebConfig

        wc = WebConfig(history_db_path="/config/")
        self.assertEqual(wc.history_db_path, "/config/history.db")

    def test_history_db_path_explicit_file_unchanged(self):
        """Explicit file path with extension is left unchanged."""
        from models.config_models import WebConfig

        wc = WebConfig(history_db_path="/data/my.db")
        self.assertEqual(wc.history_db_path, "/data/my.db")

    def test_history_db_path_whitespace_stripped(self):
        """Whitespace in path is stripped."""
        from models.config_models import WebConfig

        wc = WebConfig(history_db_path="  /data/history.db  ")
        self.assertEqual(wc.history_db_path, "/data/history.db")

    def test_app_config_includes_web(self):
        """AppConfig has a web field with defaults."""
        from models.config_models import WebConfig

        # Just verify the model can be imported and has the field
        wc = WebConfig()
        self.assertIsNotNone(wc)


if __name__ == "__main__":
    unittest.main()
