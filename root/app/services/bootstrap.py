"""Application bootstrapping, system initialization, and process registration."""

import argparse
import multiprocessing as mp
from multiprocessing.managers import SyncManager

from calibre_integration import calibre_info, calibredb_utils
from calibre_integration import factory as calibre_factory
from calibre_integration.http_client import CalibreHttpClient
from config import AppConfig
from config.ini_resolver import resolve_ini_path
from config.store import ConfigStore
import ff_logging
from history.recorder import HistoryRecorder
from history.writer import HistoryWriter
from history.recovery import recover_uncompleted_downloads
from models.context import SharedIPCContext
from notifications import notification_wrapper
from process_management import ProcessManager
from services.email_client import EmailInfo
from services import supervisor
from utils import system_utils
from workers import fff_runner, pool_runner

lazy from web import server as web_server


def log_configuration_details(
    config: AppConfig, args: argparse.Namespace, version: str
) -> None:
    """Logs detailed startup and configuration information for diagnostics."""
    ff_logging.log(f"Starting AutomatedFanfic v{version}")
    ff_logging.log(
        "For issues and updates, please go to https://github.com/MrTyton/AutomatedFanfic"
    )
    ff_logging.log(f"Using configuration file: {args.config}")

    env_info = system_utils.get_system_environment_summary()
    env_label = "Docker container" if env_info["is_docker"] else "Host system"
    ff_logging.log(
        f"Python version: {env_info['python']} ({env_info['python_implementation']})"
    )
    ff_logging.log(f"OS / Platform: {env_info['platform']} [{env_label}]")

    if calibre_factory.is_http_location(getattr(config.calibre, "path", "")):

        class _NoopLockFactory:
            @staticmethod
            def Lock():
                return None

        temp_info = calibre_info.CalibreInfo(config.calibre, _NoopLockFactory())
        calibre_version = CalibreHttpClient(temp_info, ConfigStore({})).get_version()
    else:
        calibre_version = calibredb_utils.CalibreDBClient.get_calibre_version()
    fanficfare_version = fff_runner.get_fanficfare_version()
    apprise_version = system_utils.get_installed_package_version("apprise")
    ff_logging.log(f"Calibre version: {calibre_version}")
    ff_logging.log(f"FanFicFare version: {fanficfare_version}")
    ff_logging.log(f"Apprise version: {apprise_version}")

    ff_logging.log("--- Configuration Details ---")
    try:
        ff_logging.log(f"  Email Account: {config.email.email or 'Not Specified'}")
        ff_logging.log(f"  Email Server: {config.email.server or 'Not Specified'}")
        ff_logging.log(f"  Email Mailbox: {config.email.mailbox}")
        ff_logging.log(f"  Email Sleep Time: {config.email.sleep_time}")
        ff_logging.log(
            f"  Disabled Sites: {config.email.disabled_sites if config.email.disabled_sites else 'None'}"
        )

        ff_logging.log(f"  Calibre Path: {config.calibre.path or 'Not Specified'}")
        resolved_default_ini = resolve_ini_path(
            config.calibre.default_ini, "defaults.ini"
        )
        ff_logging.log(
            f"  Calibre Default INI: {config.calibre.default_ini or (f'Packaged ({resolved_default_ini})' if resolved_default_ini else 'Packaged')}"
        )
        ff_logging.log(
            f"  Calibre Personal INI: {config.calibre.personal_ini or 'Not Specified'}"
        )
        ff_logging.log(f"  Update Method: {config.calibre.update_method}")
        ff_logging.log(f"  Update Only (email): {config.calibre.update_only}")

        mode_value = (
            config.calibre.metadata_preservation_mode.value
            if hasattr(config.calibre.metadata_preservation_mode, "value")
            else config.calibre.metadata_preservation_mode
        )
        ff_logging.log(f"  Metadata Preservation Mode: {mode_value}")

        pb_status = "Enabled" if config.pushbullet.enabled else "Disabled"
        ff_logging.log(f"  Pushbullet Notifications: {pb_status}")
        if config.pushbullet.enabled:
            ff_logging.log(
                f"  Pushbullet Device: {config.pushbullet.device or 'Not Specified'}"
            )

        if config.apprise.urls:
            ff_logging.log(
                f"  Apprise Notifications: Enabled with {len(config.apprise.urls)} target(s)"
            )
        else:
            ff_logging.log("  Apprise Notifications: Disabled")

        ff_logging.log(f"  Max Workers: {config.max_workers}")
        ff_logging.log(
            f"  Process Monitoring: {'Enabled' if config.process.enable_monitoring else 'Disabled'}"
        )
        ff_logging.log(
            f"  Auto Restart: {'Enabled' if config.process.auto_restart else 'Disabled'}"
        )

    except Exception as e:
        ff_logging.log_failure(f"  Error accessing specific configuration details: {e}")
    ff_logging.log("-----------------------------")


def register_processes(
    process_manager: ProcessManager,
    config: AppConfig,
    args: argparse.Namespace,
    manager: SyncManager,
    url_parsers: dict,
) -> None:
    """Initializes shared IPC resources and registers all worker processes with the ProcessManager."""
    is_web_enabled = bool(getattr(config.web, "enabled", False))
    _SYSTEM_OVERHEAD = 3
    overhead_count = _SYSTEM_OVERHEAD + 1 + (1 if is_web_enabled else 0)
    worker_pool_size = max(1, config.max_workers - overhead_count)

    ff_logging.log(
        f"Spawning 1 Worker Pool Process with {worker_pool_size} threads "
        f"(reserved {overhead_count} slots for support processes) "
        f"to match max_workers={config.max_workers}"
    )

    ingress_queue = mp.Queue()
    worker_queues = manager.dict()
    for i in range(worker_pool_size):
        worker_id = f"worker_{i}"
        worker_queues[worker_id] = manager.Queue()

    waiting_queue = mp.Queue()
    scale_queue = mp.Queue()
    active_urls = manager.dict()
    coordinator_status = manager.dict()

    ff_logging.set_web_enabled(is_web_enabled)
    log_queue = mp.Queue() if is_web_enabled else None

    config_store = ConfigStore(manager.dict())
    config_store.initialize_from_config(config)

    cdb_info = calibre_info.CalibreInfo(config.calibre, manager)
    calibre_client = calibre_factory.create_calibre_client(cdb_info, config_store)

    history_queue = mp.Queue(maxsize=10000)
    history_recorder = HistoryRecorder(history_queue)
    history_db_path = (
        config.web.history_db_path
        if (config.web.enabled or getattr(config.web, "history_db_path", None))
        else None
    )

    if not config.web.enabled:
        resolved_log_path = ff_logging.resolve_log_file_path(
            getattr(config.web, "log_file_path", None), history_db_path
        )
        if resolved_log_path:
            ff_logging.init_persistent_logging(resolved_log_path)

    history_writer = HistoryWriter(
        history_queue,
        history_db_path or "/data/history.db",
        shutdown_event=getattr(process_manager, "_shutdown_event", None),
    )
    history_writer.start()
    process_manager._history_writer = history_writer

    email_info = EmailInfo(
        config.email,
        config_store,
        lazy=True,
    )
    notification_info = notification_wrapper.NotificationWrapper(
        config,
        config_store,
        history_recorder,
    )

    shutdown_event = manager.Event()
    web_restart_event = mp.Event()
    supervisor_restart_event = mp.Event()
    worker_restart_event = mp.Event()
    check_emails_event = mp.Event()

    process_manager.set_config_store(config_store)
    process_manager.set_web_restart_event(web_restart_event)
    process_manager.set_supervisor_restart_event(supervisor_restart_event)
    process_manager.set_worker_restart_event(worker_restart_event)
    process_manager.set_worker_queues(worker_queues, manager.Queue)
    process_manager.set_system_overhead(overhead_count)

    ff_logging.set_log_forward_queue(log_queue)

    ipc = SharedIPCContext(
        ingress_queue=ingress_queue,
        waiting_queue=waiting_queue,
        worker_queues=worker_queues,
        active_urls=active_urls,
        history_recorder=history_recorder,
        config_store=config_store,
        scale_queue=scale_queue,
        shutdown_event=shutdown_event,
        supervisor_restart_event=supervisor_restart_event,
        worker_restart_event=worker_restart_event,
        log_queue=log_queue,
        check_emails_event=check_emails_event,
        verbose=args.verbose,
        coordinator_status=coordinator_status,
    )

    if config.retry.resume_uncompleted_on_startup and history_db_path:
        recover_uncompleted_downloads(
            history_db_path=history_db_path,
            ingress_queue=ingress_queue,
            active_urls=active_urls,
            history_recorder=history_recorder,
        )

    process_manager.register_process(
        "supervisor",
        supervisor.run_supervisor,
        args=(
            ipc,
            email_info,
            notification_info,
            url_parsers,
        ),
    )

    process_manager.register_process(
        "worker_pool",
        pool_runner.run_worker_pool,
        args=(
            ipc,
            calibre_client,
            notification_info,
            config.retry,
        ),
    )

    if config.web.enabled:
        ff_logging.log(f"Web dashboard enabled on {config.web.host}:{config.web.port}")
        process_manager.register_process(
            "web_server",
            web_server.run_web_server,
            args=(
                ipc,
                config,
                args.config,
                web_restart_event,
            ),
        )
