"""AutomatedFanfic main application module.

This module serves as the primary entry point for the AutomatedFanfic application,
orchestrating a multiprocessing-based fanfiction downloading system. The application
monitors email for fanfiction URLs, processes them through site-specific workers,
and manages downloads/updates via Calibre integration with comprehensive notification
capabilities.

Key Components:
    - Command-line argument parsing for configuration and logging control
    - TOML-based configuration loading with Pydantic validation
    - ProcessManager-coordinated multiprocessing architecture
    - Site-specific URL processing queues for scalable fanfiction handling
    - Email monitoring via IMAP for automated URL ingestion
    - Calibre database integration for e-book management
    - Notification systems (Pushbullet, Apprise) for status updates
    - Graceful shutdown handling with signal management

Architecture:
    The application uses a multiprocessing design with a ProcessManager coordinating
    worker processes. Each major fanfiction site gets its own processing queue and
    worker, while email monitoring and retry handling run in separate processes.
    All processes communicate via multiprocessing queues and are managed with
    proper signal handling for Docker compatibility.

Example:
    python fanficdownload.py --config config.toml --verbose

Author: MrTyton
Repository: https://github.com/MrTyton/AutomatedFanfic
"""

import argparse
import multiprocessing as mp
from multiprocessing.managers import SyncManager
import sys
from utils import ff_logging  # Custom logging module for formatted logging

from parsers import auto_url_parsers
from calibre_integration import calibre_info
from calibre_integration import calibredb_utils
from notifications import notification_wrapper
from services import url_ingester
from services import supervisor
from workers import pipeline as url_worker, pool_runner
from models import config_models
from models.config_models import ConfigError, ConfigValidationError
from process_management import ProcessManager

# Define the application version
__version__ = "2.4.0"


def parse_arguments() -> argparse.Namespace:
    """Parses command-line arguments for the AutomatedFanfic application.

    Creates an argument parser to handle configuration file location and logging
    verbosity settings. These arguments control core application behavior including
    configuration source and logging output detail level.

    Returns:
        argparse.Namespace: Parsed command-line arguments containing:
            - config (str): Path to the TOML configuration file
            - verbose (bool): Flag to enable detailed logging output

    Example:
        >>> args = parse_arguments()
        >>> print(args.config)  # '../config.default/config.toml'
        >>> print(args.verbose)  # False (unless --verbose flag used)
    """
    parser = argparse.ArgumentParser(description="Process input arguments.")
    # Define configuration file location with default fallback
    parser.add_argument(
        "--config",
        default="../config.default/config.toml",
        help="The location of the config.toml file",
    )
    # Enable detailed logging for debugging and monitoring
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


def setup_logging(verbose: bool) -> None:
    """Configures application logging based on verbosity settings."""
    ff_logging.set_verbose(verbose)


def load_configuration(config_path: str) -> config_models.AppConfig:
    """Loads and validates the application configuration.

    Args:
        config_path: Path to the configuration file.

    Returns:
        AppConfig: Validated configuration object or None on failure (sys.exit).
    """
    try:
        return config_models.ConfigManager.load_config(config_path)
    except ConfigError as e:
        ff_logging.log_failure(f"Configuration error: {e}")
        sys.exit(1)
    except ConfigValidationError as e:
        ff_logging.log_failure(f"Configuration validation failed: {e}")
        sys.exit(1)
    except Exception as e:
        ff_logging.log_failure(f"Unexpected error loading configuration: {e}")
        sys.exit(1)


def log_configuration_details(
    config: config_models.AppConfig, args: argparse.Namespace
) -> None:
    """Logs detailed configuration information for debugging."""
    # --- Log Version and General Configuration ---
    ff_logging.log(f"Starting AutomatedFanfic v{__version__}")
    ff_logging.log(
        "For issues and updates, please go to https://github.com/MrTyton/AutomatedFanfic"
    )
    ff_logging.log(f"Using configuration file: {args.config}")

    # Log external tool versions
    calibre_version = calibredb_utils.CalibreDBClient.get_calibre_version()
    fanficfare_version = url_worker.command.get_fanficfare_version()
    ff_logging.log(f"Calibre version: {calibre_version}")
    ff_logging.log(f"FanFicFare version: {fanficfare_version}")

    ff_logging.log("--- Configuration Details ---")
    try:
        # Log Email Configuration
        ff_logging.log(f"  Email Account: {config.email.email or 'Not Specified'}")
        ff_logging.log(f"  Email Server: {config.email.server or 'Not Specified'}")
        ff_logging.log(f"  Email Mailbox: {config.email.mailbox}")
        ff_logging.log(f"  Email Sleep Time: {config.email.sleep_time}")
        ff_logging.log(
            f"  Disabled Sites: {config.email.disabled_sites if config.email.disabled_sites else 'None'}"
        )

        # Log Calibre Configuration
        ff_logging.log(f"  Calibre Path: {config.calibre.path or 'Not Specified'}")
        ff_logging.log(
            f"  Calibre Default INI: {config.calibre.default_ini or 'Not Specified'}"
        )
        ff_logging.log(
            f"  Calibre Personal INI: {config.calibre.personal_ini or 'Not Specified'}"
        )
        ff_logging.log(f"  Update Method: {config.calibre.update_method}")

        mode_value = (
            config.calibre.metadata_preservation_mode.value
            if hasattr(config.calibre.metadata_preservation_mode, "value")
            else config.calibre.metadata_preservation_mode
        )
        ff_logging.log(f"  Metadata Preservation Mode: {mode_value}")

        # Log Pushbullet Configuration
        pb_status = "Enabled" if config.pushbullet.enabled else "Disabled"
        ff_logging.log(f"  Pushbullet Notifications: {pb_status}")
        if config.pushbullet.enabled:
            ff_logging.log(
                f"  Pushbullet Device: {config.pushbullet.device or 'Not Specified'}"
            )

        # Log Apprise Configuration
        if config.apprise.urls:
            ff_logging.log(
                f"  Apprise Notifications: Enabled with {len(config.apprise.urls)} target(s)"
            )
        else:
            ff_logging.log("  Apprise Notifications: Disabled")

        # Log Process Configuration
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
    config: config_models.AppConfig,
    args: argparse.Namespace,
    manager: SyncManager,
    url_parsers: dict,
) -> None:
    """Registers all worker processes with the ProcessManager."""
    # Register Worker Pool (Single Process with Threads)
    # We use all available slots for threads as they are lightweight, but we respect the
    # max_workers limit as a "System Process Limit" since each thread spawns a subprocess.
    # Overhead: Main(1) + SyncManager(1) + Coordinator(1) + Email(1) + Waiter(1) + ResourceTracker(1) = 6
    overhead_count = 4
    worker_pool_size = max(1, config.max_workers - overhead_count)

    ff_logging.log(
        f"Spawning 1 Worker Pool Process with {worker_pool_size} threads "
        f"(reserved {overhead_count} slots for support processes) "
        f"to match max_workers={config.max_workers}"
    )

    ingress_queue = manager.Queue()
    worker_queues = {}
    for i in range(worker_pool_size):
        worker_id = f"worker_{i}"
        worker_queues[worker_id] = manager.Queue()

    waiting_queue = manager.Queue()
    active_urls = manager.dict()

    # Initialize Calibre components
    cdb_info = calibre_info.CalibreInfo(args.config, manager)
    cdb_info.check_installed()
    calibre_client = calibredb_utils.CalibreDBClient(cdb_info)

    # Initialize external resources
    email_info = url_ingester.EmailInfo(config.email)
    notification_info = notification_wrapper.NotificationWrapper(toml_path=args.config)

    # Register Supervisor Process (Hosts Email, Waiter, Coordinator)
    process_manager.register_process(
        "supervisor",
        supervisor.run_supervisor,
        args=(
            worker_queues,
            ingress_queue,
            waiting_queue,
            email_info,
            notification_info,
            url_parsers,
            active_urls,
            args.verbose,
        ),
    )

    # Register the single pool process that hosts all worker threads
    process_manager.register_process(
        "worker_pool",
        pool_runner.run_worker_pool,
        args=(
            worker_queues,
            calibre_client,
            notification_info,
            ingress_queue,
            config.retry,
            active_urls,
            args.verbose,
        ),
    )


def main() -> None:
    """Main application entry point."""
    args = parse_arguments()
    setup_logging(args.verbose)
    config = load_configuration(args.config)

    # Initialize logging with config details
    log_configuration_details(config, args)

    # Use ProcessManager for robust process handling
    with ProcessManager(config=config) as process_manager:
        with mp.Manager() as manager:
            ff_logging.log("Generating URL parsers from FanFicFare adapters...")
            url_parsers = auto_url_parsers.generate_url_parsers_from_fanficfare()
            ff_logging.log(
                f"Generated {len(url_parsers)} URL parsers for site recognition"
            )

            register_processes(process_manager, config, args, manager, url_parsers)

            ff_logging.log("Starting all processes...")
            process_manager.start_all()
            ff_logging.log("All processes started successfully")
            ff_logging.log("Processes running. Press Ctrl+C to stop gracefully.")

            try:
                process_manager.wait_for_all()
                ff_logging.log("All processes completed normally")

            except KeyboardInterrupt:
                ff_logging.log(
                    "KeyboardInterrupt caught - signal handler may not have handled shutdown",
                    "WARNING",
                )
                if not process_manager._shutdown_event.is_set():
                    ff_logging.log(
                        "Initiating manual shutdown due to KeyboardInterrupt"
                    )
                    process_manager.stop_all()

                if not process_manager.wait_for_all(timeout=30.0):
                    ff_logging.log_failure(
                        "Timeout waiting for processes after manual shutdown"
                    )
                else:
                    ff_logging.log("Manual shutdown completed successfully")

    ff_logging.log("Application shutdown complete")


if __name__ == "__main__":
    main()
