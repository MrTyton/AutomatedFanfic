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

    def test_get_resolved_default_ini(self):
        store = ConfigStore()
        # Default without config falls back to packaged defaults.ini
        resolved = store.get_resolved_default_ini()
        self.assertTrue(resolved.endswith("defaults.ini"))

        # Explicit directory appends defaults.ini
        store.update("calibre.default_ini", "/custom/dir")
        self.assertTrue(store.get_resolved_default_ini().endswith("defaults.ini"))

    def test_get_resolved_personal_ini(self):
        store = ConfigStore()
        # Default without config returns empty string
        self.assertEqual(store.get_resolved_personal_ini(), "")

        # Explicit directory appends personal.ini
        store.update("calibre.personal_ini", "/custom/dir")
        self.assertTrue(store.get_resolved_personal_ini().endswith("personal.ini"))

    def test_get_fff_configuration_and_callable(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p_ini = os.path.join(tmp_dir, "personal.ini")
            with open(p_ini, "w", encoding="utf-8") as f:
                f.write("[archiveofourown.org]\nusername=storeuser\n")

            store = ConfigStore()
            store.update("calibre.personal_ini", p_ini)

            config = store.get_fff_configuration(
                "https://archiveofourown.org/series/12345"
            )
            self.assertTrue(config.has_section("archiveofourown.org"))
            self.assertEqual(config.get("archiveofourown.org", "username"), "storeuser")

            callable_fn = store.get_fff_get_configuration_callable()
            self.assertTrue(callable(callable_fn))
            config2 = callable_fn("https://archiveofourown.org/series/12345")
            self.assertEqual(
                config2.get("archiveofourown.org", "username"), "storeuser"
            )

    def test_version_counter_increments_and_excluded_from_get_all(self):
        store = ConfigStore()
        self.assertIsNone(store.get_version())
        store.update("email.sleep_time", 60)
        v1 = store.get_version()
        self.assertEqual(v1, 1)
        store.update_many({"email.sleep_time": 120, "calibre.path": "/lib"})
        v2 = store.get_version()
        self.assertEqual(v2, 2)
        self.assertNotIn("__version__", store.get_all())

    def test_read_ini_file_cached_invalidates_on_change(self):
        from config.config_store import read_ini_file_cached

        with tempfile.TemporaryDirectory() as tmp_dir:
            ini_path = os.path.join(tmp_dir, "personal.ini")
            with open(ini_path, "w", encoding="utf-8") as f:
                f.write("[defaults]\nval=1\n")

            first = read_ini_file_cached(ini_path)
            self.assertIn("val=1", first or "")

            # Modify file content & size so (mtime_ns, size) invalidates cache
            with open(ini_path, "w", encoding="utf-8") as f:
                f.write("[defaults]\nval=updated_value_2\n")

            second = read_ini_file_cached(ini_path)
            self.assertIn("val=updated_value_2", second or "")
            self.assertIsNone(
                read_ini_file_cached(os.path.join(tmp_dir, "missing.ini"))
            )


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
        # Web fields are the only SERVICE_RESTART fields now
        self.assertEqual(
            ConfigStore.get_reload_behavior("web", "port"),
            ReloadBehavior.SERVICE_RESTART,
        )
        self.assertEqual(
            ConfigStore.get_reload_behavior("web", "host"),
            ReloadBehavior.SERVICE_RESTART,
        )

    def test_app_restart_fields(self):
        # process.max_workers is now HOT (dynamic scaling via manager.dict())
        self.assertEqual(
            ConfigStore.get_reload_behavior("process", "max_workers"),
            ReloadBehavior.HOT,
        )
        # Email/calibre credentials are now HOT
        self.assertEqual(
            ConfigStore.get_reload_behavior("email", "password"),
            ReloadBehavior.HOT,
        )
        self.assertEqual(
            ConfigStore.get_reload_behavior("calibre", "path"),
            ReloadBehavior.HOT,
        )

    def test_unknown_defaults_to_app_restart(self):
        self.assertEqual(
            ConfigStore.get_reload_behavior("unknown", "field"),
            ReloadBehavior.APP_RESTART,
        )

    def test_classify_changes_mixed(self):
        changes = {
            "sleep_time": 120,  # hot
            "password": "new_pass",  # also hot now
        }
        classified = ConfigStore.classify_changes("email", changes)
        self.assertIn("sleep_time", classified[ReloadBehavior.HOT])
        self.assertIn("password", classified[ReloadBehavior.HOT])
        self.assertEqual(classified[ReloadBehavior.SERVICE_RESTART], {})
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
        import threading

        q = mp.Queue()
        wq = {"w-1": mp.Queue(), "w-2": mp.Queue()}
        from services.coordinator import Coordinator

        coord = Coordinator(
            q,
            wq,
            threading.Event(),
            {},
            MagicMock(),
            {},
            ConfigStore(),
            scale_queue=mp.Queue(),
        )
        snap = coord.get_state_snapshot()
        self.assertEqual(snap["backlog"], {})
        self.assertEqual(snap["assignments"], {})
        self.assertIn("w-1", snap["idle_workers"])
        self.assertIn("w-2", snap["idle_workers"])

    def test_snapshot_with_backlog_and_assignments(self):
        import collections
        import multiprocessing as mp
        import threading

        from models.fanfic_info import FanficInfo
        from services.coordinator import Coordinator

        q = mp.Queue()
        wq = {"w-1": mp.Queue()}
        coord = Coordinator(
            q,
            wq,
            threading.Event(),
            {},
            MagicMock(),
            {},
            ConfigStore(),
            scale_queue=mp.Queue(),
        )

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
            "process": {"max_workers": 4},
        }
        self.state.config = cfg

        resp = self.client.get("/api/config")
        data = resp.json()
        self.assertIn("reload_map", data)
        self.assertEqual(
            data["reload_map"]["email"]["sleep_time"]["reload_behavior"], "hot"
        )
        self.assertEqual(
            data["reload_map"]["process"]["max_workers"]["reload_behavior"], "hot"
        )

    def test_get_reload_map(self):
        """GET /api/config/reload-map returns full field mapping."""
        resp = self.client.get("/api/config/reload-map")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["email.sleep_time"], "hot")
        # Credentials are now HOT (no restart needed)
        self.assertEqual(data["email.password"], "hot")
        # Web fields are SERVICE_RESTART (auto-restarted by ProcessManager)
        self.assertEqual(data["web.port"], "service_restart")

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
        """Changing web.* fields is flagged as service_restart (auto web restart)."""
        cfg = MagicMock()
        cfg.model_dump.return_value = {"web": {"host": "0.0.0.0", "port": 8080}}
        self.state.config = cfg
        self.state.config_store = ConfigStore()
        self.state.config_path = "/tmp/config.toml"

        resp = self.client.put("/api/config/web", json={"values": {"port": 9090}})
        data = resp.json()
        self.assertTrue(data["applied"])
        self.assertIn("port", data["results"]["service_restart"])
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
