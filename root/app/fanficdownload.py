import argparse
import multiprocessing as mp
import sys
import time
from typing import Any
import ff_logging  # Custom logging module for formatted logging

import calibre_info
import ff_waiter
import notification_wrapper
import regex_parsing
import url_ingester
import url_worker
from config_models import ConfigManager, ConfigError, ConfigValidationError
from process_manager import ProcessManager

# Define the application version
__version__ = "1.4.1"


def parse_arguments() -> argparse.Namespace:
    """
    Parses command-line arguments.

    Returns:
        Namespace: An argparse.Namespace object containing all the arguments.
                   Currently, it includes '--config' for specifying the config
                   file location and '--verbose' for enabling verbose logging.
    """
    parser = argparse.ArgumentParser(description="Process input arguments.")
    parser.add_argument(
        "--config",
        default="../config.default/config.toml",
        help="The location of the config.toml file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


def main():
    """
    Main function to orchestrate the fanfic downloading process.
    """
    args = parse_arguments()

    ff_logging.set_verbose(args.verbose)

    # --- Log Version and General Configuration ---
    ff_logging.log(f"Starting AutomatedFanfic v{__version__}")
    ff_logging.log(
        "For issues and updates, please go to https://github.com/MrTyton/AutomatedFanfic"
    )
    ff_logging.log(f"Using configuration file: {args.config}")

    # Load and validate configuration using the new system
    try:
        config = ConfigManager.load_config(args.config)
    except ConfigError as e:
        ff_logging.log_failure(f"Configuration error: {e}")
        sys.exit(1)
    except ConfigValidationError as e:
        ff_logging.log_failure(f"Configuration validation failed: {e}")
        sys.exit(1)
    except Exception as e:
        ff_logging.log_failure(f"Unexpected error loading configuration: {e}")
        sys.exit(1)

    # --- Log Specific Configuration Details ---
    # Initialize NotificationWrapper early for logging
    notification_info = notification_wrapper.NotificationWrapper(toml_path=args.config)

    ff_logging.log("--- Configuration Details ---")
    try:
        # Log Email Configuration
        ff_logging.log(f"  Email Account: {config.email.email or 'Not Specified'}")
        ff_logging.log(f"  Email Server: {config.email.server or 'Not Specified'}")
        ff_logging.log(f"  Email Mailbox: {config.email.mailbox}")
        ff_logging.log(f"  Email Sleep Time: {config.email.sleep_time}")
        ff_logging.log(f"  FFNet Disabled: {config.email.ffnet_disable}")

        # Log Calibre Configuration
        ff_logging.log(f"  Calibre Path: {config.calibre.path or 'Not Specified'}")
        ff_logging.log(
            f"  Calibre Default INI: {config.calibre.default_ini or 'Not Specified'}"
        )
        ff_logging.log(
            f"  Calibre Personal INI: {config.calibre.personal_ini or 'Not Specified'}"
        )

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
    # --- End Logging ---

    # Initialize configurations for email
    email_info = url_ingester.EmailInfo(args.config)

    # Use ProcessManager for robust process handling
    with ProcessManager(config=config) as process_manager:
        with mp.Manager() as manager:
            # Create queues for each site and a waiting queue for delayed processing
            queues = {
                site: manager.Queue() for site in regex_parsing.url_parsers.keys()
            }
            waiting_queue = manager.Queue()
            cdb_info = calibre_info.CalibreInfo(args.config, manager)
            cdb_info.check_installed()

            # Register email watcher process
            process_manager.register_process(
                "email_watcher",
                url_ingester.email_watcher,
                args=(email_info, notification_info, queues),
            )

            # Register waiting watcher process
            process_manager.register_process(
                "waiting_watcher",
                ff_waiter.wait_processor,
                args=(queues, waiting_queue),
            )

            # Register URL worker processes for each site
            for site in queues.keys():
                process_manager.register_process(
                    f"worker_{site}",
                    url_worker.url_worker,
                    args=(queues[site], cdb_info, notification_info, waiting_queue),
                )

            # Start all processes with monitoring and graceful shutdown
            ff_logging.log("Starting all processes...")
            process_manager.start_all()
            ff_logging.log("All processes started successfully")

            # The ProcessManager context manager will handle graceful shutdown
            ff_logging.log("Processes running. Press Ctrl+C to stop gracefully.")

            # Keep the main thread alive while processes run
            try:
                # Wait for processes to complete (they run indefinitely until stopped)
                process_manager.wait_for_all()  # Wait indefinitely for normal completion
            except KeyboardInterrupt:
                # KeyboardInterrupt (Ctrl+C) generates SIGINT, which should be handled
                # by ProcessManager's signal handlers. The signal handler will call
                # stop_all() to initiate graceful shutdown of all child processes.
                ff_logging.log(
                    "Received interrupt signal, waiting for processes to complete...",
                    "WARNING",
                )

                # Wait for all processes to actually terminate after signal handler
                # called stop_all(). This ensures we don't exit before children are done.
                # Use a reasonable timeout to prevent hanging indefinitely
                if not process_manager.wait_for_all(timeout=300.0):
                    ff_logging.log_failure(
                        "Timeout waiting for processes - forcing shutdown"
                    )
                else:
                    ff_logging.log("All processes completed graceful shutdown")

    ff_logging.log("Application shutdown complete")


if __name__ == "__main__":
    main()
