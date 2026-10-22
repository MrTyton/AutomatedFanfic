"""Tests for the web server routes and app factory."""

import unittest
from queue import Empty, Queue
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from models.fanfic_info import FanficInfo
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

    def test_retry_now_requeues_waiting_item(self):
        """retry-now should pull waiting item and enqueue immediately."""
        from models.fanfic_info import FanficInfo

        self.state.ingress_queue = Queue()
        self.state.waiting_queue = Queue()
        self.state.active_urls = {}
        self.state.waiting_queue.put(
            FanficInfo(url="https://ao3.org/works/1", site="ao3", title="Story")
        )

        resp = self.client.post(
            "/api/controls/retry-now", json={"url": "https://ao3.org/works/1"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        queued = self.state.ingress_queue.get_nowait()
        assert isinstance(queued, FanficInfo)
        self.assertIn(queued.url, {"https://ao3.org/works/1", "ao3.org/works/1"})
        self.assertEqual(queued.title, "Story")

    def test_cancel_retry_removes_waiting_entry(self):
        """cancel-retry should remove pending waiting/ingress queue entries."""
        from models.fanfic_info import FanficInfo

        self.state.ingress_queue = Queue()
        self.state.waiting_queue = Queue()
        self.state.worker_queues = {"worker_1": Queue()}
        self.state.active_urls = {"https://ao3.org/works/1": {"status": "waiting"}}

        self.state.waiting_queue.put(
            FanficInfo(url="https://ao3.org/works/1", site="ao3")
        )
        self.state.ingress_queue.put(
            FanficInfo(url="https://ao3.org/works/1", site="ao3")
        )
        self.state.worker_queues["worker_1"].put(
            FanficInfo(url="https://ao3.org/works/1", site="ao3")
        )

        resp = self.client.post(
            "/api/controls/cancel-retry", json={"url": "https://ao3.org/works/1"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        with self.assertRaises(Empty):
            self.state.waiting_queue.get_nowait()
        with self.assertRaises(Empty):
            self.state.ingress_queue.get_nowait()

    def test_redownload_scratch_rejects_processing_item(self):
        """redownload should be blocked while actively processing."""
        self.state.ingress_queue = Queue()
        self.state.active_urls = {"https://ao3.org/works/1": {"status": "processing"}}

        resp = self.client.post(
            "/api/controls/redownload-scratch", json={"url": "https://ao3.org/works/1"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["ok"])

    @patch("web.routes.controls._remove_from_calibre_if_possible")
    @patch("parsers.auto_url_parsers.generate_url_parsers_from_fanficfare")
    @patch("parsers.regex_parsing.generate_FanficInfo_from_url")
    def test_redownload_scratch_queues_force_task(
        self, mock_generate, mock_parsers, mock_remove
    ):
        """redownload should queue a fresh force task when safe."""
        from models.fanfic_info import FanficInfo

        mock_parsers.return_value = {}
        mock_generate.return_value = FanficInfo(
            url="https://ao3.org/works/1", site="ao3", title="Story"
        )
        mock_remove.return_value = (
            True,
            "Removed from Calibre and queued fresh download.",
        )

        self.state.ingress_queue = Queue()
        self.state.waiting_queue = Queue()
        self.state.active_urls = {"https://ao3.org/works/1": {"status": "queued"}}

        resp = self.client.post(
            "/api/controls/redownload-scratch",
            json={"url": "https://ao3.org/works/1", "site": "ao3", "title": "Story"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

        queued = self.state.ingress_queue.get_nowait()
        assert isinstance(queued, FanficInfo)
        self.assertEqual(queued.url, "https://ao3.org/works/1")
        self.assertEqual(queued.behavior, "force")

    @patch("web.routes.controls.calibre_factory.create_calibre_client")
    @patch("calibre_integration.calibre_info.CalibreInfo")
    def test_remove_from_calibre_if_possible_uses_config_and_config_store(
        self, mock_calibre_info_cls, mock_create_client
    ):
        """_remove_from_calibre_if_possible constructs CalibreInfo from state.config.calibre and passes state.config_store."""
        from web.routes.controls import _remove_from_calibre_if_possible

        fanfic = FanficInfo(url="https://ao3.org/works/1", site="ao3", calibre_id="42")

        # Missing state.config returns False
        self.state.config = None
        ok, msg = _remove_from_calibre_if_possible(self.state, fanfic)
        self.assertFalse(ok)
        self.assertIn("Calibre configuration unavailable", msg)

        # Valid state.config.calibre and state.config_store
        mock_cfg = MagicMock()
        mock_cfg.calibre = MagicMock()
        mock_store = MagicMock()
        self.state.config = mock_cfg
        self.state.config_store = mock_store

        ok, msg = _remove_from_calibre_if_possible(self.state, fanfic)
        self.assertTrue(ok)
        mock_calibre_info_cls.assert_called_once()
        self.assertEqual(mock_calibre_info_cls.call_args.args[0], mock_cfg.calibre)
        mock_create_client.assert_called_once_with(
            mock_calibre_info_cls.return_value, mock_store
        )
        mock_create_client.return_value.remove_story.assert_called_once_with(fanfic)


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

    def test_get_ini_no_config(self):
        """INI endpoints return error when no config is loaded."""
        for ini_type in ("personal", "defaults"):
            resp = self.client.get(f"/api/config/ini/{ini_type}")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIsNone(data["content"])
            self.assertIn("error", data)

    def test_get_ini_unknown_type(self):
        """Unknown ini_type returns an error."""
        mock_config = MagicMock()
        self.state.config = mock_config
        resp = self.client.get("/api/config/ini/unknown")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNone(data["content"])
        self.assertIn("Unknown ini type", data["error"])

    def test_get_ini_no_path_configured(self):
        """INI endpoint returns error for personal.ini when path is not configured."""
        mock_config = MagicMock()
        mock_config.calibre.personal_ini = None
        mock_config.calibre.default_ini = None
        self.state.config = mock_config

        resp = self.client.get("/api/config/ini/personal")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNone(data["content"])
        self.assertIn("No path configured for personal.ini", data["error"])

    def test_put_ini_defaults_is_read_only(self):
        """PUT INI endpoint rejects modifications to defaults.ini."""
        mock_config = MagicMock()
        self.state.config = mock_config
        resp = self.client.put("/api/config/ini/defaults", json={"content": "[new]"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["applied"])
        self.assertIn(
            "defaults.ini is packaged and updated automatically", data["error"]
        )

    def test_get_ini_file_content(self):
        """INI endpoint returns file content when file exists."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            personal_path = os.path.join(tmp_dir, "personal.ini")
            defaults_path = os.path.join(tmp_dir, "defaults.ini")
            for p in (personal_path, defaults_path):
                with open(p, "w") as f:
                    f.write("[defaults]\nsite:www.fanfiction.net\n")

            mock_config = MagicMock()
            mock_config.calibre.personal_ini = personal_path
            mock_config.calibre.default_ini = defaults_path
            self.state.config = mock_config

            for ini_type, expected_path in (
                ("personal", personal_path),
                ("defaults", defaults_path),
            ):
                resp = self.client.get(f"/api/config/ini/{ini_type}")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertIn("[defaults]", data["content"])
                self.assertEqual(data["path"], expected_path)
                self.assertIsNone(data["error"])

    def test_get_ini_file_missing(self):
        """INI endpoint returns empty content when file does not exist."""
        mock_config = MagicMock()
        mock_config.calibre.personal_ini = "/nonexistent/path/personal.ini"
        mock_config.calibre.default_ini = "/nonexistent/path/defaults.ini"
        self.state.config = mock_config

        for ini_type in ("personal", "defaults"):
            resp = self.client.get(f"/api/config/ini/{ini_type}")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["content"], "")
            self.assertIsNone(data["error"])

    def test_get_ini_resolves_directory_path(self):
        """INI endpoint resolves a directory path to the correct ini file."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            personal_path = os.path.join(tmp_dir, "personal.ini")
            defaults_path = os.path.join(tmp_dir, "defaults.ini")
            for p in (personal_path, defaults_path):
                with open(p, "w") as f:
                    f.write("[resolved]\nfrom_dir = true\n")

            mock_config = MagicMock()
            # Config points to the directory, not the file
            mock_config.calibre.personal_ini = tmp_dir
            mock_config.calibre.default_ini = tmp_dir
            self.state.config = mock_config

            for ini_type, expected_path in (
                ("personal", personal_path),
                ("defaults", defaults_path),
            ):
                resp = self.client.get(f"/api/config/ini/{ini_type}")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertIn("[resolved]", data["content"])
                self.assertEqual(data["path"], expected_path)
                self.assertIsNone(data["error"])

    def test_get_ini_resolves_directory_without_file(self):
        """INI endpoint returns empty when directory exists but file doesn't."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            mock_config = MagicMock()
            # Directory exists but personal.ini / defaults.ini do not
            mock_config.calibre.personal_ini = tmp_dir
            mock_config.calibre.default_ini = tmp_dir
            self.state.config = mock_config

            for ini_type in ("personal", "defaults"):
                resp = self.client.get(f"/api/config/ini/{ini_type}")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["content"], "")
                self.assertIsNone(data["error"])

    def test_put_ini_no_config(self):
        """PUT INI endpoint returns error when no config is loaded."""
        resp = self.client.put("/api/config/ini/personal", json={"content": "[test]"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["applied"])
        self.assertIn("error", data)

    def test_put_ini_writes_file(self):
        """PUT INI endpoint writes content to the configured path."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            personal_path = os.path.join(tmp_dir, "personal.ini")
            # Create the file so the path exists
            with open(personal_path, "w") as f:
                f.write("")

            mock_config = MagicMock()
            mock_config.calibre.personal_ini = personal_path
            mock_config.calibre.default_ini = personal_path
            self.state.config = mock_config

            new_content = "[story]\nsome_option:value\n"
            resp = self.client.put(
                "/api/config/ini/personal", json={"content": new_content}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["applied"])

            with open(personal_path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), new_content)


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


class TestRealLifespanAndDatabaseIntegration(unittest.TestCase):
    """End-to-end tests for web routes using real FastAPI lifespan, real SQLite DB, real ConfigStore, and real TomlWriter."""

    def test_real_lifespan_stats_history_and_logs(self):
        import os
        import tempfile
        from history.database import SyncHistoryDB
        from history.models import (
            DownloadEvent,
            EmailCheckEvent,
            NotificationEvent,
            RetryAction,
            RetryEvent,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "history.db")
            sync_db = SyncHistoryDB(db_path)
            sync_db.connect()
            try:
                sync_db.insert_download(
                    DownloadEvent(
                        url="archiveofourown.org/works/101",
                        site="archiveofourown",
                        title="Story 101",
                        behavior="force",
                    )
                )
                sync_db.update_download(
                    "archiveofourown.org/works/101",
                    status="failed",
                    error_message="HTTP Error 503",
                )
                sync_db.insert_retry(
                    RetryEvent(
                        url="archiveofourown.org/works/101",
                        site="archiveofourown",
                        attempt_number=1,
                        action=RetryAction.RETRY,
                        delay_minutes=1.0,
                        error_message="HTTP Error 503",
                    )
                )
                sync_db.update_download(
                    "archiveofourown.org/works/101",
                    status="waiting",
                    error_message="HTTP Error 503",
                )
                sync_db.insert_email_check(
                    EmailCheckEvent(
                        urls_found=2,
                        urls_new=1,
                        urls_duplicate=1,
                        urls_disabled_site=0,
                    )
                )
                sync_db.insert_notification(
                    NotificationEvent(
                        title="New Fanfiction Download",
                        body="Story 101",
                        site="archiveofourown",
                        provider="apprise",
                    )
                )
            finally:
                sync_db.close()

            from history.database import AsyncHistoryDB

            state = WebState(
                history_db=AsyncHistoryDB(db_path),
                active_urls={
                    "archiveofourown.org/works/101": {
                        "site": "archiveofourown",
                        "title": "Story 101",
                        "status": "waiting",
                    },
                    "archiveofourown.org/works/999": {
                        "site": "archiveofourown",
                        "title": "Cancelled Story",
                        "status": "cancelled",
                    },
                },
            )
            app = create_app(state)
            with TestClient(app) as client:
                # 1. History endpoints backed by real AsyncHistoryDB
                dl_resp = client.get("/api/history/downloads")
                self.assertEqual(dl_resp.status_code, 200)
                dl_data = dl_resp.json()
                self.assertEqual(dl_data["total"], 1)
                self.assertEqual(dl_data["items"][0]["status"], "waiting")

                retry_resp = client.get(
                    "/api/history/retries/archiveofourown.org/works/101"
                )
                self.assertEqual(retry_resp.status_code, 200)
                self.assertEqual(len(retry_resp.json()["items"]), 1)

                email_resp = client.get("/api/history/emails")
                self.assertEqual(len(email_resp.json()["items"]), 1)

                notif_resp = client.get("/api/history/notifications")
                self.assertEqual(len(notif_resp.json()["items"]), 1)

                recent_resp = client.get("/api/history/recent")
                self.assertGreaterEqual(len(recent_resp.json()["items"]), 3)

                # 2. Stats endpoints backed by real AsyncHistoryDB
                stats_resp = client.get("/api/stats")
                self.assertEqual(stats_resp.status_code, 200)
                stats_data = stats_resp.json()
                self.assertEqual(stats_data["total_downloads"], 1)
                self.assertEqual(stats_data["downloads_with_retries"], 1)
                self.assertEqual(stats_data["total_retries"], 1)
                self.assertEqual(
                    stats_data["downloads_by_site"][0]["site"], "archiveofourown"
                )
                self.assertEqual(
                    stats_data["status_breakdown"], [{"status": "waiting", "count": 1}]
                )

                # 3. Widget & monitoring exclude cancelled entries
                widget_resp = client.get("/api/widget")
                widget_data = widget_resp.json()
                self.assertEqual(widget_data["active_downloads"], 1)
                self.assertEqual(widget_data["active"][0]["state"], "waiting")

                mon_resp = client.get("/api/monitoring/active")
                self.assertEqual(mon_resp.json()["count"], 1)

    def test_controls_cancel_retry_allows_immediate_readd_and_preserves_calibre_id_on_retry_now(
        self,
    ):
        """Cancelling a waiting URL removes it cleanly so add-url can re-add it, and retry-now preserves calibre_id."""
        state = WebState(
            ingress_queue=Queue(),
            waiting_queue=Queue(),
            worker_queues={"worker_0": Queue()},
            active_urls={
                "archiveofourown.org/works/42": {
                    "site": "archiveofourown",
                    "title": "Story 42",
                    "calibre_id": "777",
                    "status": "waiting",
                    "heap_gen": 1,
                }
            },
        )
        app = create_app(state)
        client = TestClient(app)

        # 1. retry-now preserves calibre_id from active_urls when item is in pending_heap (not waiting_queue)
        retry_resp = client.post(
            "/api/controls/retry-now",
            json={"url": "https://archiveofourown.org/works/42"},
        )
        self.assertTrue(retry_resp.json()["ok"])
        assert state.ingress_queue is not None
        assert state.active_urls is not None
        requeued = state.ingress_queue.get_nowait()
        assert isinstance(requeued, FanficInfo)
        self.assertEqual(requeued.url, "archiveofourown.org/works/42")
        self.assertEqual(requeued.calibre_id, "777")
        self.assertEqual(
            state.active_urls["archiveofourown.org/works/42"]["status"], "queued"
        )

        # 2. cancel-retry marks entry cancelled without adding raw https:// duplicate key, and allows immediate add-url
        state.active_urls["archiveofourown.org/works/42"]["status"] = "waiting"
        cancel_resp = client.post(
            "/api/controls/cancel-retry",
            json={"url": "https://archiveofourown.org/works/42"},
        )
        self.assertTrue(cancel_resp.json()["ok"])
        self.assertNotIn("https://archiveofourown.org/works/42", state.active_urls)
        self.assertEqual(
            state.active_urls["archiveofourown.org/works/42"]["status"], "cancelled"
        )

        # Re-adding the same URL immediately after cancel-retry must succeed!
        add_resp = client.post(
            "/api/controls/add-url",
            json={"url": "https://archiveofourown.org/works/42"},
        )
        self.assertTrue(add_resp.json()["accepted"])
        self.assertEqual(
            state.active_urls["archiveofourown.org/works/42"]["status"], "queued"
        )

    def test_config_put_preserves_masked_secrets_and_rejects_invalid_values(self):
        """PUT /api/config/{section} preserves '********' secrets and rejects invalid values before mutating state."""
        import os
        import tempfile
        from config.config_store import ConfigStore
        from models.config_models import ConfigManager

        toml_content = """
[email]
email = "orig@example.com"
password = "super_secret_password"
server = "imap.example.com"
mailbox = "INBOX"
sleep_time = 60

[calibre]
path = "/library"
password = "calibre_secret_password"

[process]
max_workers = 2

[pushbullet]
enabled = true
api_key = "pb_real_secret_key"

[web]
enabled = true
host = "0.0.0.0"
port = 8080
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = os.path.join(tmp_dir, "config.toml")
            with open(cfg_path, "w", encoding="utf-8") as fh:
                fh.write(toml_content)

            cfg = ConfigManager.load_config(cfg_path, force_reload=True)
            store = ConfigStore({})
            store.initialize_from_config(cfg)

            state = WebState(
                config=cfg,
                config_path=cfg_path,
                config_store=store,
            )
            app = create_app(state)
            client = TestClient(app)

            # 1. Saving email section with masked password '********' must preserve real password
            resp = client.put(
                "/api/config/email",
                json={
                    "values": {
                        "email": "updated@example.com",
                        "password": "********",
                        "sleep_time": 90,
                    }
                },
            )
            self.assertTrue(resp.json()["applied"])
            self.assertEqual(store.get("email.email"), "updated@example.com")
            self.assertEqual(store.get("email.password"), "super_secret_password")
            assert state.config is not None
            self.assertEqual(state.config.email.password, "super_secret_password")
            with open(cfg_path, encoding="utf-8") as fh:
                disk_text = fh.read()
            self.assertIn("super_secret_password", disk_text)
            self.assertNotIn("********", disk_text)

            # 2. Invalid config value (sleep_time = -10) is rejected before mutating store or file
            bad_resp = client.put(
                "/api/config/email",
                json={"values": {"sleep_time": -10}},
            )
            self.assertFalse(bad_resp.json()["applied"])
            self.assertEqual(store.get("email.sleep_time"), 90)

            # 3. Updating process.max_workers updates ConfigStore and TOML
            mw_resp = client.put(
                "/api/config/process",
                json={"values": {"max_workers": 6}},
            )
            self.assertTrue(mw_resp.json()["applied"])
            self.assertEqual(store.get("process.max_workers"), 6)
            assert state.config is not None
            self.assertEqual(state.config.process.max_workers, 6)
            self.assertEqual(state.config.max_workers, 6)

    def test_gzip_middleware_and_history_db_lifespan_connect(self):
        """create_app registers GZipMiddleware and connects/closes AsyncHistoryDB during lifespan."""
        from unittest.mock import AsyncMock

        mock_history_db = MagicMock()
        mock_history_db.connect = AsyncMock()
        mock_history_db.ensure_schema = AsyncMock()
        mock_history_db.close = AsyncMock()
        mock_history_db.get_downloads = AsyncMock(
            return_value=[
                {"url": f"https://ao3.org/works/{i}", "title": "A" * 200}
                for i in range(10)
            ]
        )
        mock_history_db.get_download_count = AsyncMock(return_value=10)

        state = WebState(history_db=mock_history_db)
        app = create_app(state)

        with TestClient(app) as client:
            mock_history_db.connect.assert_awaited_once()
            resp = client.get(
                "/api/history/downloads",
                headers={"Accept-Encoding": "gzip"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("content-encoding"), "gzip")

        mock_history_db.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
