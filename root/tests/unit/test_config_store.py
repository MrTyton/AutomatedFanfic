"""Tests for config store, TOML writer, coordinator snapshot, and updated config routes."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import tomlkit
from fastapi.testclient import TestClient

from config.config_store import (
    ConfigStore,
    ReloadBehavior,
)
from config.toml_writer import TomlWriter
from web.dependencies import WebState
from web.server import create_app


# ── ConfigStore ─────────────────────────────────────────────────────


class TestConfigStoreBasics(unittest.TestCase):
    def test_get_set(self):
        store = ConfigStore()
        store.update("email.sleep_time", 120)
        self.assertEqual(store.get("email.sleep_time"), 120)

    def test_get_default(self):
        store = ConfigStore()
        self.assertIsNone(store.get("nonexistent"))
        self.assertEqual(store.get("nonexistent", 42), 42)

    def test_update_many(self):
        store = ConfigStore()
        store.update_many({"a": 1, "b": 2})
        self.assertEqual(store.get("a"), 1)
        self.assertEqual(store.get("b"), 2)

    def test_get_all(self):
        store = ConfigStore({"x": 10, "y": 20})
        snapshot = store.get_all()
        self.assertEqual(snapshot, {"x": 10, "y": 20})
        # Snapshot should be a copy
        snapshot["z"] = 30
        self.assertIsNone(store.get("z"))


class TestConfigStoreInitFromConfig(unittest.TestCase):
    def _make_config(self):
        cfg = MagicMock()
        cfg.email.sleep_time = 90
        cfg.email.disabled_sites = ["ffnet"]
        cfg.calibre.update_method = "update_always"
        cfg.calibre.metadata_preservation_mode.value = "preserve_metadata"
        cfg.retry.max_normal_retries = 5
        cfg.retry.hail_mary_enabled = False
        cfg.retry.hail_mary_wait_hours = 6.0
        return cfg

    def test_initialize_populates_all_keys(self):
        store = ConfigStore()
        store.initialize_from_config(self._make_config())
        self.assertEqual(store.get("email.sleep_time"), 90)
        self.assertEqual(store.get("email.disabled_sites"), ["ffnet"])
        self.assertEqual(store.get("calibre.update_method"), "update_always")
        self.assertEqual(
            store.get("calibre.metadata_preservation_mode"), "preserve_metadata"
        )
        self.assertEqual(store.get("retry.max_normal_retries"), 5)
        self.assertFalse(store.get("retry.hail_mary_enabled"))
        self.assertEqual(store.get("retry.hail_mary_wait_hours"), 6.0)


class TestReloadBehaviorClassification(unittest.TestCase):
    def test_hot_fields(self):
        self.assertEqual(
            ConfigStore.get_reload_behavior("email", "sleep_time"),
            ReloadBehavior.HOT,
        )
        self.assertEqual(
            ConfigStore.get_reload_behavior("retry", "max_normal_retries"),
            ReloadBehavior.HOT,
        )

    def test_service_restart_fields(self):
        self.assertEqual(
            ConfigStore.get_reload_behavior("email", "password"),
            ReloadBehavior.SERVICE_RESTART,
        )
        self.assertEqual(
            ConfigStore.get_reload_behavior("calibre", "path"),
            ReloadBehavior.SERVICE_RESTART,
        )

    def test_app_restart_fields(self):
        self.assertEqual(
            ConfigStore.get_reload_behavior("", "max_workers"),
            ReloadBehavior.APP_RESTART,
        )
        self.assertEqual(
            ConfigStore.get_reload_behavior("web", "port"),
            ReloadBehavior.APP_RESTART,
        )

    def test_unknown_defaults_to_app_restart(self):
        self.assertEqual(
            ConfigStore.get_reload_behavior("unknown", "field"),
            ReloadBehavior.APP_RESTART,
        )

    def test_classify_changes_mixed(self):
        changes = {
            "sleep_time": 120,  # hot
            "password": "new_pass",  # service_restart
        }
        classified = ConfigStore.classify_changes("email", changes)
        self.assertIn("sleep_time", classified[ReloadBehavior.HOT])
        self.assertIn("password", classified[ReloadBehavior.SERVICE_RESTART])
        self.assertEqual(classified[ReloadBehavior.APP_RESTART], {})


# ── TomlWriter ──────────────────────────────────────────────────────


class TestTomlWriter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        )
        self.tmp.write(
            '[email]\nemail = "user@test.com"\nsleep_time = 60\n\n[calibre]\npath = "/lib"\n'
        )
        self.tmp.close()
        self.writer = TomlWriter(self.tmp.name)

    def tearDown(self):
        for p in [
            self.tmp.name,
            self.tmp.name + ".bak",
            self.tmp.name.replace(".toml", ".toml.bak"),
        ]:
            if os.path.exists(p):
                os.unlink(p)
        # Also clean the .bak path created by backup()
        bak = Path(self.tmp.name).with_suffix(".toml.bak")
        if bak.exists():
            bak.unlink()

    def test_read_raw(self):
        data = self.writer.read_raw()
        self.assertEqual(data["email"]["email"], "user@test.com")
        self.assertEqual(data["email"]["sleep_time"], 60)

    def test_read_tomlkit_preserves_type(self):
        doc = self.writer.read_tomlkit()
        self.assertIsInstance(doc, tomlkit.TOMLDocument)

    def test_backup_creates_file(self):
        bak = self.writer.backup()
        self.assertTrue(bak.exists())

    def test_write_section_updates_value(self):
        self.writer.write_section("email", {"sleep_time": 120})
        data = self.writer.read_raw()
        self.assertEqual(data["email"]["sleep_time"], 120)
        # Original email field preserved
        self.assertEqual(data["email"]["email"], "user@test.com")

    def test_write_section_creates_backup(self):
        bak = self.writer.write_section("email", {"sleep_time": 120})
        self.assertTrue(bak.exists())

    def test_write_section_new_section(self):
        self.writer.write_section("retry", {"max_normal_retries": 5})
        data = self.writer.read_raw()
        self.assertEqual(data["retry"]["max_normal_retries"], 5)

    def test_write_preserves_other_sections(self):
        self.writer.write_section("email", {"sleep_time": 120})
        data = self.writer.read_raw()
        self.assertEqual(data["calibre"]["path"], "/lib")


# ── Coordinator.get_state_snapshot ──────────────────────────────────


class TestCoordinatorSnapshot(unittest.TestCase):
    def test_snapshot_empty_state(self):
        import multiprocessing as mp

        q = mp.Queue()
        wq = {"w-1": mp.Queue(), "w-2": mp.Queue()}
        from services.coordinator import Coordinator

        coord = Coordinator(q, wq)
        snap = coord.get_state_snapshot()
        self.assertEqual(snap["backlog"], {})
        self.assertEqual(snap["assignments"], {})
        self.assertIn("w-1", snap["idle_workers"])
        self.assertIn("w-2", snap["idle_workers"])

    def test_snapshot_with_backlog_and_assignments(self):
        import collections
        import multiprocessing as mp

        from models.fanfic_info import FanficInfo
        from services.coordinator import Coordinator

        q = mp.Queue()
        wq = {"w-1": mp.Queue()}
        coord = Coordinator(q, wq)

        # Manually set state
        fanfic = FanficInfo(url="https://ao3.org/works/1", site="ao3")
        coord.state.backlog["ao3"] = collections.deque([fanfic])
        coord.state.assignments["ffnet"] = "w-1"
        coord.state.idle_workers = set()

        snap = coord.get_state_snapshot()
        self.assertEqual(snap["backlog"]["ao3"], ["https://ao3.org/works/1"])
        self.assertEqual(snap["assignments"]["ffnet"], "w-1")
        self.assertEqual(snap["idle_workers"], [])


# ── Updated Config Routes ───────────────────────────────────────────


class TestConfigRoutesUpdated(unittest.TestCase):
    def setUp(self):
        self.state = WebState()
        self.app = create_app(self.state)
        self.client = TestClient(self.app)

    def test_get_config_includes_reload_map(self):
        """GET /api/config now returns reload_map alongside config."""
        cfg = MagicMock()
        cfg.model_dump.return_value = {
            "email": {"sleep_time": 60, "password": "secret"},
            "max_workers": 4,
        }
        self.state.config = cfg

        resp = self.client.get("/api/config")
        data = resp.json()
        self.assertIn("reload_map", data)
        self.assertEqual(
            data["reload_map"]["email"]["sleep_time"]["reload_behavior"], "hot"
        )
        self.assertEqual(
            data["reload_map"]["max_workers"]["reload_behavior"], "app_restart"
        )

    def test_get_reload_map(self):
        """GET /api/config/reload-map returns full field mapping."""
        resp = self.client.get("/api/config/reload-map")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["email.sleep_time"], "hot")
        self.assertEqual(data["email.password"], "service_restart")

    def test_put_config_no_config(self):
        resp = self.client.put(
            "/api/config/email", json={"values": {"sleep_time": 120}}
        )
        data = resp.json()
        self.assertFalse(data["applied"])

    def test_put_config_unknown_section(self):
        cfg = MagicMock()
        cfg.model_dump.return_value = {"email": {"sleep_time": 60}}
        self.state.config = cfg

        resp = self.client.put("/api/config/bogus", json={"values": {"x": 1}})
        data = resp.json()
        self.assertFalse(data["applied"])
        self.assertIn("Unknown section", data["error"])

    @patch("web.routes.config.TomlWriter")
    def test_put_config_hot_reload(self, MockWriter):
        """Hot-reloadable fields get written to ConfigStore immediately."""
        cfg = MagicMock()
        cfg.model_dump.return_value = {"email": {"sleep_time": 60, "password": "x"}}
        self.state.config = cfg

        store = ConfigStore()
        store.update("email.sleep_time", 60)
        self.state.config_store = store
        self.state.config_path = "/tmp/config.toml"

        resp = self.client.put(
            "/api/config/email", json={"values": {"sleep_time": 120}}
        )
        data = resp.json()
        self.assertTrue(data["applied"])
        self.assertIn("sleep_time", data["results"]["hot"])
        self.assertFalse(data["needs_service_restart"])
        self.assertFalse(data["needs_app_restart"])
        # Verify store was updated
        self.assertEqual(store.get("email.sleep_time"), 120)

    @patch("web.routes.config.TomlWriter")
    def test_put_config_service_restart(self, MockWriter):
        """Service-restart field is flagged in the response."""
        cfg = MagicMock()
        cfg.model_dump.return_value = {"email": {"sleep_time": 60, "password": "x"}}
        self.state.config = cfg
        self.state.config_store = ConfigStore()
        self.state.config_path = "/tmp/config.toml"

        resp = self.client.put(
            "/api/config/email", json={"values": {"password": "new_pass"}}
        )
        data = resp.json()
        self.assertTrue(data["applied"])
        self.assertIn("password", data["results"]["service_restart"])
        self.assertTrue(data["needs_service_restart"])

    def test_validate_config_with_real_config(self):
        """POST /api/config/validate merges and validates with Pydantic."""
        from models.config_models import AppConfig, EmailConfig, CalibreConfig

        cfg = AppConfig(
            email=EmailConfig(email="a@b.com", password="p", server="imap.test"),
            calibre=CalibreConfig(path="/lib"),
        )
        self.state.config = cfg

        resp = self.client.post(
            "/api/config/validate",
            json={
                "values": {
                    "email": {
                        "email": "new@b.com",
                        "password": "p",
                        "server": "imap.test",
                    },
                    "calibre": {"path": "/lib"},
                }
            },
        )
        data = resp.json()
        self.assertTrue(data["valid"])
