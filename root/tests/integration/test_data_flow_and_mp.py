"""End-to-end cross-component data flow and multiprocessing (spawn) integration tests.

These tests verify real interactions across components with minimal mocking:
- Worker pipeline -> handlers -> update_strategies -> ff_waiter -> HistoryRecorder -> HistoryWriter -> SyncHistoryDB / AsyncHistoryDB
- Series expansion in Coordinator with real FanFicFare URL parsers, active_urls cleanup, and HistoryRecorder
- ConfigStore hot-reload propagation into RetryConfig, NotificationWrapper/AppriseNotification, and CalibreInfo
- True multiprocessing 'spawn' pickling of all process arguments (EmailInfo with INI closures, CalibreDBClient, NotificationWrapper, RetryConfig, HistoryRecorder)
"""

import asyncio
import multiprocessing as mp
import os
from pathlib import Path
from queue import Queue
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from fanficfare.adapters.base_adapter import BaseSiteAdapter

from calibre_integration.calibre_info import CalibreInfo
from calibre_integration.calibredb_utils import CalibreDBClient
from config.config_store import ConfigStore
from history.database import AsyncHistoryDB, SyncHistoryDB
from history.recorder import HistoryRecorder, HistoryWriter
from models import config_models
from models.active_urls import ActiveUrlsDict
from models.fanfic_info import FanficInfo
from notifications.notification_wrapper import NotificationWrapper
from parsers.auto_url_parsers import generate_url_parsers_from_fanficfare
from services import supervisor
from services.coordinator import Coordinator
from services.ff_waiter import wait_processor
from services.url_ingester import EmailInfo
from models.context import SharedIPCContext
from workers import command, pipeline


def _child_verify_supervisor_process_boot(
    ipc: SharedIPCContext,
    email_info: EmailInfo,
    notification_info: NotificationWrapper,
    url_parsers: dict,
    result_queue: mp.Queue,
) -> None:
    """Execute supervisor in a spawned child process with real SyncManager proxies.

    Verifies that all three helper threads (EmailWatcher, Waiter, Coordinator)
    boot successfully and remain healthy without crashing.
    """
    stop_requested = threading.Event()

    def _watchdog() -> None:
        # Wait long enough for supervisor to boot and complete its first health-check iteration
        time.sleep(1.5)
        if ipc.shutdown_event.is_set():
            result_queue.put(
                {
                    "ok": False,
                    "error": "Supervisor shut down prematurely due to thread failure",
                }
            )
            return
        stop_requested.set()
        ipc.shutdown_event.set()
        try:
            ipc.ingress_queue.put(None)
        except Exception:
            pass
        try:
            ipc.waiting_queue.put(None)
        except Exception:
            pass

    watchdog = threading.Thread(target=_watchdog, daemon=True)
    watchdog.start()

    try:
        supervisor.run_supervisor(
            ipc,
            email_info,
            notification_info,
            url_parsers,
        )
        if not stop_requested.is_set():
            result_queue.put(
                {
                    "ok": False,
                    "error": "Supervisor exited before shutdown was requested",
                }
            )
        else:
            result_queue.put({"ok": True})
    except Exception as exc:
        result_queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def _child_verify_spawn_objects(
    email_info: EmailInfo,
    calibre_client: CalibreDBClient,
    notification_info: NotificationWrapper,
    retry_config: config_models.RetryConfig,
    history_recorder: HistoryRecorder,
    config_store: ConfigStore,
    result_queue: mp.Queue,
) -> None:
    """Top-level function executed in a 'spawn' child process to verify pickling and live ConfigStore access."""
    try:
        # Attach config_store in child as pool_runner does
        calibre_client.set_config_store(config_store)
        notification_info.set_config_store(config_store)
        retry_config.set_config_store(config_store)

        # Verify ConfigStore values are visible and syncable in child process
        email_changed = email_info.update_from_config_store(config_store)
        retry_changed = retry_config.update_from_config_store()
        calibre_changed = calibre_client.cdb_info.update_from_config_store(config_store)

        # Emit a history event from the child process
        history_recorder.record_download_created(
            "archiveofourown.org/works/99999", "archiveofourown", "update"
        )

        result_queue.put(
            {
                "ok": True,
                "email": email_info.email,
                "has_geturls": email_info._geturls is not None,
                "max_normal_retries": retry_config.max_normal_retries,
                "calibre_update_method": calibre_client.cdb_info.update_method,
                "email_changed": email_changed,
                "retry_changed": retry_changed,
                "calibre_changed": calibre_changed,
                "default_ini": email_info.default_ini,
            }
        )
    except Exception as exc:
        result_queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class TestDataFlowAndMultiprocessingIntegration(unittest.TestCase):
    """End-to-end integration tests for data flow, state transitions, and multiprocessing."""

    def test_full_retry_lifecycle_single_db_row_and_waiter_flow(self):
        """A download that fails, waits in ff_waiter, retries, and succeeds must maintain a single download_events row and accurate active_urls state."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "history.db")
            history_q = Queue()
            recorder = HistoryRecorder(history_q)
            writer = HistoryWriter(history_q, db_path)
            writer.start()

            try:
                ingress_q = Queue()
                waiting_q = Queue()
                worker_q = Queue()
                worker_queues = {"worker_0": worker_q}
                active_urls = {}
                store = ConfigStore({})

                url_parsers = generate_url_parsers_from_fanficfare()
                coordinator = Coordinator(
                    ingress_q,
                    worker_queues,
                    shutdown_event=threading.Event(),
                    active_urls=active_urls,
                    history_recorder=recorder,
                    url_parsers=url_parsers,
                    config_store=store,
                    scale_queue=Queue(),
                )

                # Step 1: Ingest URL (as email_watcher or add-url does)
                story_url = "archiveofourown.org/works/77777"
                fanfic = FanficInfo(
                    url=story_url,
                    site="archiveofourown",
                    title="Retry Lifecycle Story",
                )
                active_urls[story_url] = {
                    "site": "archiveofourown",
                    "title": "Retry Lifecycle Story",
                    "status": "queued",
                }
                recorder.record_download_created(story_url, "archiveofourown")
                ingress_q.put(fanfic)

                # Coordinator routes to worker_0
                coordinator._process_single_ingress_item(timeout=0.1)
                self.assertFalse(worker_q.empty())

                # Set up mock Calibre client and NotificationWrapper
                mock_cdb_info = MagicMock(spec=CalibreInfo)
                mock_cdb_info.update_method = "update"
                mock_cdb_info.metadata_preservation_mode = (
                    config_models.MetadataPreservationMode.ADD_FORMAT
                )
                mock_client = MagicMock(spec=CalibreDBClient)
                mock_client.cdb_info = mock_cdb_info
                mock_client.get_story_id.return_value = None
                mock_notif = MagicMock(spec=NotificationWrapper)
                retry_cfg = config_models.RetryConfig(
                    max_normal_retries=5,
                    hail_mary_enabled=True,
                    hail_mary_wait_hours=12.0,
                )

                from models.context import WorkerContext

                worker_ctx = WorkerContext(
                    calibre_client=mock_client,
                    notification_info=mock_notif,
                    ingress_queue=ingress_q,
                    waiting_queue=waiting_q,
                    retry_config=retry_cfg,
                    history_recorder=recorder,
                    active_urls=active_urls,
                )

                # Step 2: Run worker for Attempt 1 (fails in FanFicFare)
                worker_q.put(None)  # Poison pill after 1st item
                with (
                    patch(
                        "workers.pipeline.system_utils.temporary_directory"
                    ) as mock_td,
                    patch("workers.common.get_path_or_url", return_value=story_url),
                    patch(
                        "workers.command.execute_fanficfare_direct",
                        return_value=command.FanFicFareResult(
                            failure_messages=["HTTP Error 503 Service Unavailable"]
                        ),
                    ),
                ):
                    mock_td.return_value.__enter__.return_value = tmp_dir
                    pipeline.url_worker(
                        worker_q,
                        worker_ctx,
                        "worker_0",
                        False,
                    )

                # Drain Coordinator's WORKER_IDLE signal from worker_0 exit
                while not ingress_q.empty():
                    coordinator._process_single_ingress_item(timeout=0.1)

                # Verify active_urls kept the story with status == 'waiting'
                self.assertIn(story_url, active_urls)
                self.assertEqual(active_urls[story_url]["status"], "waiting")

                # Wait briefly for HistoryWriter to flush to SQLite
                time.sleep(0.15)
                sync_db = SyncHistoryDB(db_path)
                sync_db.connect()
                try:
                    rows = sync_db.conn.execute(
                        "SELECT id, url, status, error_message, completed_at FROM download_events"
                    ).fetchall()
                    self.assertEqual(
                        len(rows),
                        1,
                        f"Expected exactly 1 download_events row, got {len(rows)}: {rows}",
                    )
                    _, _, row_status, row_err, row_completed = rows[0]
                    self.assertEqual(row_status, "waiting")
                    self.assertIn("HTTP Error 503", row_err)
                    self.assertIsNone(row_completed)
                finally:
                    sync_db.close()

                # Step 3: Run ff_waiter to pop the waiting item and fire retry
                waiting_item = waiting_q.get_nowait()
                # Override delay_minutes to 0 so wait_processor fires immediately
                waiting_item.retry_decision = waiting_item.retry_decision._replace(
                    delay_minutes=0.0
                )
                waiting_q.put(waiting_item)
                waiting_q.put(None)  # Poison pill so wait_processor exits after firing

                wait_processor(
                    ingress_q,
                    waiting_q,
                    verbose=False,
                    shutdown_event=threading.Event(),
                    history_recorder=recorder,
                    active_urls=active_urls,
                )

                self.assertFalse(ingress_q.empty())
                self.assertEqual(active_urls[story_url]["status"], "queued")

                # Step 4: Route retried task through Coordinator to worker_0 and succeed on Attempt 2
                coordinator._process_single_ingress_item(timeout=0.1)
                worker_q.put(None)

                def add_story_success(location, fanfic):
                    fanfic.calibre_id = "888"

                mock_client.add_story.side_effect = add_story_success

                with (
                    patch(
                        "workers.pipeline.system_utils.temporary_directory"
                    ) as mock_td,
                    patch("workers.common.get_path_or_url", return_value=story_url),
                    patch(
                        "workers.command.execute_fanficfare_direct",
                        return_value=command.FanFicFareResult(),
                    ),
                ):
                    mock_td.return_value.__enter__.return_value = tmp_dir
                    pipeline.url_worker(
                        worker_q,
                        worker_ctx,
                        "worker_0",
                        False,
                    )

            finally:
                writer.stop()

            # Step 5: Verify final SQLite state via AsyncHistoryDB and SyncHistoryDB
            self.assertNotIn(story_url, active_urls)

            async def verify_async_db():
                adb = AsyncHistoryDB(db_path)
                await adb.ensure_schema()
                try:
                    downloads = await adb.get_downloads()
                    retries = await adb.get_retries_for_url(story_url)
                    return downloads, retries
                finally:
                    await adb.close()

            downloads, retries = asyncio.run(verify_async_db())
            self.assertEqual(
                len(downloads),
                1,
                f"Expected single download row across entire retry lifecycle, got {len(downloads)}",
            )
            self.assertEqual(downloads[0]["status"], "success")
            self.assertEqual(downloads[0]["calibre_id"], "888")
            self.assertIsNone(downloads[0]["error_message"])
            self.assertIsNotNone(downloads[0]["completed_at"])

            self.assertEqual(len(retries), 1)
            self.assertEqual(retries[0]["attempt_number"], 1)
            self.assertIsNotNone(retries[0]["fired_at"])

    def test_coordinator_series_expansion_cleans_parent_and_registers_children(self):
        """Series expansion in Coordinator removes parent series URL from active_urls and normalizes/records child story URLs."""
        series_html = """
        <html><body>
          <div class="series-show">
            <h2 class="heading">Expanded Series</h2>
            <dl class="series meta group"><dd><dl class="stats"><dd class="words">100</dd></dl></dd></dl>
            <ul class="series work index group">
              <li class="work blurb group"><h4 class="heading"><a href="/works/1001">Work 1</a></h4></li>
              <li class="work blurb group"><h4 class="heading"><a href="/works/1002">Work 2</a></h4></li>
            </ul>
          </div>
        </body></html>
        """
        ingress_q = Queue()
        worker_queues = {"worker_0": Queue(), "worker_1": Queue()}
        history_q = Queue()
        recorder = HistoryRecorder(history_q)
        url_parsers = generate_url_parsers_from_fanficfare()

        series_url = "archiveofourown.org/series/3039543"
        active_urls: ActiveUrlsDict = {
            series_url: {"site": "archiveofourown", "status": "queued"}
        }

        coordinator = Coordinator(
            ingress_q,
            worker_queues,
            shutdown_event=threading.Event(),
            active_urls=active_urls,
            history_recorder=recorder,
            url_parsers=url_parsers,
            config_store=ConfigStore({}),
            scale_queue=Queue(),
        )

        ingress_q.put(FanficInfo(url=series_url, site="archiveofourown"))
        with patch.object(BaseSiteAdapter, "get_request", return_value=series_html):
            coordinator._process_single_ingress_item(timeout=0.1)

        # Parent series URL must be removed from active_urls
        self.assertNotIn(series_url, active_urls)
        # Child URLs must be normalized (schemeless) and registered in active_urls
        self.assertIn("archiveofourown.org/works/1001", active_urls)
        self.assertIn("archiveofourown.org/works/1002", active_urls)

        # HistoryRecorder must have recorded download_created for both child stories
        events = []
        while not history_q.empty():
            events.append(history_q.get_nowait())
        created_urls = [
            e["payload"]["url"] for e in events if e["event_type"] == "download_created"
        ]
        self.assertEqual(
            created_urls,
            [
                "archiveofourown.org/works/1001",
                "archiveofourown.org/works/1002",
            ],
        )

    def test_config_store_hot_reload_across_calibre_notifications_and_retry(self):
        """ConfigStore changes propagate to RetryConfig, NotificationWrapper/AppriseNotification, and CalibreInfo without false error logs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = os.path.join(tmp_dir, "config.toml")
            with open(cfg_path, "w", encoding="utf-8") as fh:
                fh.write(
                    f'[email]\nemail = "u"\npassword = "p"\nserver = "s"\n'
                    f'[calibre]\npath = "{tmp_dir.replace(chr(92), "/")}"\n'
                    f'default_ini = "{tmp_dir.replace(chr(92), "/")}"\n'
                    f'personal_ini = "{tmp_dir.replace(chr(92), "/")}"\n'
                    f"[apprise]\nurls = []\n"
                )

            cfg = config_models.ConfigManager.load_config(cfg_path, force_reload=True)
            store = ConfigStore({})
            store.initialize_from_config(cfg)

            # 1. CalibreInfo does not spam log_failure on repeated update_from_config_store when INI files are absent
            dummy_mgr = MagicMock()
            cdb_info = CalibreInfo(cfg.calibre, dummy_mgr)
            with patch(
                "calibre_integration.calibre_info.ff_logging.log_failure"
            ) as mock_log_fail:
                cdb_info.update_from_config_store(store)
                cdb_info.update_from_config_store(store)
                mock_log_fail.assert_not_called()

            # Creating personal.ini on disk is automatically detected on next update_from_config_store
            personal_ini_path = os.path.join(tmp_dir, "personal.ini")
            with open(personal_ini_path, "w", encoding="utf-8") as fh:
                fh.write("[defaults]\n")
            self.assertTrue(cdb_info.update_from_config_store(store))
            self.assertEqual(Path(cdb_info.personal_ini), Path(personal_ini_path))

            # 2. NotificationWrapper hot-reloads new Apprise URLs from ConfigStore even without editing config.toml
            recorder = HistoryRecorder(Queue())
            wrapper = NotificationWrapper(cfg, store, recorder)
            self.assertEqual(len(wrapper.notification_workers), 0)

            store.update("apprise.urls", ["json://localhost:8080/notify"])
            wrapper._refresh_if_changed()
            self.assertEqual(len(wrapper.notification_workers), 1)
            self.assertIn(
                "json://localhost:8080/notify",
                getattr(wrapper.notification_workers[0], "apprise_urls", []),
            )

            # 3. RetryConfig hot-reloads max_normal_retries and hail_mary_enabled from ConfigStore inside handle_failure
            from workers import handlers

            retry_cfg = config_models.RetryConfig(
                max_normal_retries=11, hail_mary_enabled=True
            )
            retry_cfg.set_config_store(store)
            store.update("retry.max_normal_retries", 1)
            store.update("retry.hail_mary_enabled", False)

            from models.context import WorkerContext

            fanfic = FanficInfo(
                url="archiveofourown.org/works/1",
                site="archiveofourown",
                title="Test",
                repeats=0,
            )
            waiting_q = Queue()
            ctx = WorkerContext(
                calibre_client=MagicMock(cdb_info=None),
                notification_info=MagicMock(),
                ingress_queue=Queue(),
                waiting_queue=waiting_q,
                retry_config=retry_cfg,
                history_recorder=recorder,
                active_urls={},
            )
            handlers.handle_failure(fanfic, ctx)
            self.assertEqual(retry_cfg.max_normal_retries, 1)
            self.assertFalse(retry_cfg.hail_mary_enabled)
            # With max_normal_retries=1 and hail_mary_enabled=False, repeats=0 -> 1 is ABANDON!
            self.assertIsNotNone(fanfic.retry_decision)
            assert fanfic.retry_decision is not None
            self.assertEqual(fanfic.retry_decision.action.value, "abandon")
            self.assertTrue(waiting_q.empty())

    def test_spawn_multiprocessing_pickling_of_all_process_arguments(self):
        """All objects passed to child processes must survive 'spawn' pickling and sync with a live mp.Manager ConfigStore."""
        defaults_ini = str(
            Path(__file__).resolve().parents[2] / "config.default" / "defaults.ini"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = os.path.join(tmp_dir, "config.toml")
            with open(cfg_path, "w", encoding="utf-8") as fh:
                fh.write(
                    f'[email]\nemail = "initial@example.com"\npassword = "p"\nserver = "imap.test"\n'
                    f'[calibre]\npath = "{tmp_dir.replace(chr(92), "/")}"\nupdate_method = "update"\n'
                )

            cfg = config_models.ConfigManager.load_config(cfg_path, force_reload=True)

            with mp.Manager() as manager:
                store = ConfigStore(manager.dict())
                store.initialize_from_config(cfg)

                # Mutate ConfigStore in parent before spawning child
                store.update("email.email", "hotreloaded@example.com")
                store.update("retry.max_normal_retries", 7)
                store.update("calibre.update_method", "force")
                store.update("fanficfare.default_ini", defaults_ini)

                history_q = manager.Queue()
                recorder = HistoryRecorder(history_q)
                email_info = EmailInfo(cfg.email, store)
                cdb_info = CalibreInfo(cfg.calibre, manager)
                calibre_client = CalibreDBClient(cdb_info, store)
                notification_info = NotificationWrapper(cfg, store, recorder)
                retry_config = cfg.retry
                result_q = manager.Queue()

                ctx = mp.get_context("spawn")
                proc = ctx.Process(
                    target=_child_verify_spawn_objects,
                    args=(
                        email_info,
                        calibre_client,
                        notification_info,
                        retry_config,
                        recorder,
                        store,
                        result_q,
                    ),
                )
                proc.start()
                proc.join(timeout=20)
                self.assertEqual(proc.exitcode, 0)

                res = result_q.get(timeout=5)
                self.assertTrue(res["ok"], f"Child process failed: {res}")
                self.assertEqual(res["email"], "hotreloaded@example.com")
                self.assertTrue(res["has_geturls"])
                self.assertEqual(res["max_normal_retries"], 7)
                self.assertEqual(res["calibre_update_method"], "force")
                self.assertTrue(res["email_changed"])
                self.assertTrue(res["retry_changed"])
                self.assertTrue(res["calibre_changed"])
                self.assertEqual(res["default_ini"], defaults_ini)

                # Verify child's HistoryRecorder event reached parent's queue
                msg = history_q.get(timeout=5)
                self.assertEqual(msg["event_type"], "download_created")
                self.assertEqual(
                    msg["payload"]["url"], "archiveofourown.org/works/99999"
                )

    def test_supervisor_process_spawn_with_real_manager_proxies(self):
        """Regression test: Supervisor process must start in a spawned child process with real SyncManager proxies without thread death."""
        cfg = config_models.AppConfig(
            email=config_models.EmailConfig(
                email="test@example.com",
                password="pass",
                server="imap.example.com",
                mailbox="INBOX",
                sleep_time=60,
                imap_idle=False,
            ),
            calibre=config_models.CalibreConfig(),
        )
        store = ConfigStore({})
        store.initialize_from_config(cfg)

        with mp.Manager() as manager:
            worker_queues = manager.dict(
                {
                    "worker_0": manager.Queue(),
                    "worker_1": manager.Queue(),
                }
            )
            ingress_q = manager.Queue()
            waiting_q = manager.Queue()
            scale_q = manager.Queue()
            history_q = manager.Queue()
            active_urls = manager.dict()

            recorder = HistoryRecorder(history_q)
            email_info = EmailInfo(cfg.email, store, lazy=True)
            notification_info = NotificationWrapper(cfg, store, recorder)
            url_parsers = generate_url_parsers_from_fanficfare()

            shutdown_event = manager.Event()
            ipc = SharedIPCContext(
                ingress_queue=ingress_q,
                waiting_queue=waiting_q,
                worker_queues=worker_queues,
                active_urls=active_urls,
                history_recorder=recorder,
                config_store=store,
                scale_queue=scale_q,
                shutdown_event=shutdown_event,
                verbose=False,
            )

            result_q = manager.Queue()
            ctx = mp.get_context("spawn")
            proc = ctx.Process(
                target=_child_verify_supervisor_process_boot,
                args=(ipc, email_info, notification_info, url_parsers, result_q),
            )
            proc.start()
            proc.join(timeout=10)

            self.assertEqual(
                proc.exitcode,
                0,
                f"Supervisor process exited with non-zero code {proc.exitcode}",
            )
            res = result_q.get(timeout=2)
            self.assertTrue(res["ok"], f"Supervisor boot failed: {res.get('error')}")


if __name__ == "__main__":
    unittest.main()
