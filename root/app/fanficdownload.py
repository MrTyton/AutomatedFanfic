"""AutomatedFanfic main application module.

This module serves as the primary entry point for the AutomatedFanfic application,
orchestrating an asyncio-based fanfiction downloading system. The application
monitors email for fanfiction URLs, processes them through site-specific workers,
and manages downloads/updates via Calibre integration with comprehensive notification
capabilities.

Key Components:
    - Command-line argument parsing for configuration and logging control
    - TOML-based configuration loading with Pydantic validation
    - TaskManager-coordinated asyncio architecture
    - Site-specific URL processing queues for scalable fanfiction handling
    - Email monitoring via IMAP for automated URL ingestion
    - Calibre database integration for e-book management
    - Notification systems (Pushbullet, Apprise) for status updates
    - Graceful shutdown handling with signal management

Architecture:
    The application uses an asyncio design with a TaskManager coordinating
    worker tasks. Each major fanfiction site gets its own processing queue and
    worker, while email monitoring and retry handling run in separate tasks.
    All tasks communicate via asyncio queues and are managed with
    proper signal handling for Docker compatibility.

Example:
    python fanficdownload.py --config config.toml --verbose

Author: MrTyton
Repository: https://github.com/MrTyton/AutomatedFanfic
"""

import argparse
import asyncio
import sys
import ff_logging  # Custom logging module for formatted logging

import auto_url_parsers
import calibre_info
import calibredb_utils
import ff_waiter
import notification_wrapper
import url_ingester
import url_worker
from config_models import ConfigManager, ConfigError, ConfigValidationError
from task_manager import TaskManager

# Define the application version
__version__ = "1.13.1"


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


async def async_main() -> None:
    """Main application entry point that orchestrates the fanfiction downloading process.

    Initializes the complete AutomatedFanfic workflow including configuration loading,
    task management setup, email monitoring, URL processing workers, and graceful
    shutdown handling. Uses asyncio architecture with coordinated worker
    tasks for different fanfiction sites.

    The function creates a robust processing pipeline:
    1. Parses command-line arguments and loads configuration
    2. Initializes notification and email monitoring systems
    3. Creates site-specific processing queues for URL handling
    4. Starts coordinated worker tasks under TaskManager supervision
    5. Handles graceful shutdown via signal handling and cleanup

    Raises:
        ConfigError: If configuration file cannot be loaded or parsed.
        ConfigValidationError: If configuration values fail validation.
        SystemExit: On configuration errors or unexpected failures during startup.

    Note:
        This function runs indefinitely until interrupted by signal (SIGTERM/SIGINT)
        or manual termination. TaskManager handles coordinated shutdown of all
        worker tasks with proper cleanup and timeout handling.
    """
    args = parse_arguments()

    # Configure logging verbosity based on command-line flag
    ff_logging.set_verbose(args.verbose)

    # --- Log Version and General Configuration ---
    ff_logging.log(f"Starting AutomatedFanfic v{__version__}")
    ff_logging.log(
        "For issues and updates, please go to https://github.com/MrTyton/AutomatedFanfic"
    )
    ff_logging.log(f"Using configuration file: {args.config}")

    # Log external tool versions
    calibre_version = calibredb_utils.get_calibre_version()
    fanficfare_version = url_worker.get_fanficfare_version()
    ff_logging.log(f"Calibre version: {calibre_version}")
    ff_logging.log(f"FanFicFare version: {fanficfare_version}")

    # Load and validate configuration using the new system
    try:
        # Load TOML configuration with comprehensive validation
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
    # Initialize NotificationWrapper early for comprehensive startup logging
    notification_info = notification_wrapper.NotificationWrapper(toml_path=args.config)

    ff_logging.log("--- Configuration Details ---")
    try:
        # Log Email Configuration - IMAP settings and processing behavior
        ff_logging.log(f"  Email Account: {config.email.email or 'Not Specified'}")
        ff_logging.log(f"  Email Server: {config.email.server or 'Not Specified'}")
        ff_logging.log(f"  Email Mailbox: {config.email.mailbox}")
        ff_logging.log(f"  Email Sleep Time: {config.email.sleep_time}")
        ff_logging.log(
            f"  Disabled Sites: {config.email.disabled_sites if config.email.disabled_sites else 'None'}"
        )

        # Log Calibre Configuration - Library and processing settings
        ff_logging.log(f"  Calibre Path: {config.calibre.path or 'Not Specified'}")
        ff_logging.log(
            f"  Calibre Default INI: {config.calibre.default_ini or 'Not Specified'}"
        )
        ff_logging.log(
            f"  Calibre Personal INI: {config.calibre.personal_ini or 'Not Specified'}"
        )
        ff_logging.log(f"  Update Method: {config.calibre.update_method}")

        # Log Pushbullet Configuration - Mobile notification settings
        pb_status = "Enabled" if config.pushbullet.enabled else "Disabled"
        ff_logging.log(f"  Pushbullet Notifications: {pb_status}")
        if config.pushbullet.enabled:
            ff_logging.log(
                f"  Pushbullet Device: {config.pushbullet.device or 'Not Specified'}"
            )

        # Log Apprise Configuration - Multi-platform notification settings
        if config.apprise.urls:
            ff_logging.log(
                f"  Apprise Notifications: Enabled with {len(config.apprise.urls)} target(s)"
            )
        else:
            ff_logging.log("  Apprise Notifications: Disabled")

        # Log Process Configuration - Worker and monitoring settings
        ff_logging.log(f"  Max Workers: {config.max_workers}")
        ff_logging.log(
            f"  Task Monitoring: {'Enabled' if config.process.enable_monitoring else 'Disabled'}"
        )
        ff_logging.log(
            f"  Auto Restart: {'Enabled' if config.process.auto_restart else 'Disabled'}"
        )

    except Exception as e:
        ff_logging.log_failure(f"  Error accessing specific configuration details: {e}")
    ff_logging.log("-----------------------------")
    # --- End Logging ---

    # Initialize configurations for email monitoring and processing
    email_info = url_ingester.EmailInfo(config.email)

    # Use TaskManager for robust task handling with signal management
    async with TaskManager(config=config) as task_manager:
        # Generate URL parsers once in the main task to avoid loading adapters in each worker
        ff_logging.log("Generating URL parsers from FanFicFare adapters...")
        url_parsers = auto_url_parsers.generate_url_parsers_from_fanficfare()
        ff_logging.log(
            f"Generated {len(url_parsers)} URL parsers for site recognition"
        )

        # Create site-specific queues for URL processing parallelization
        queues = {site: asyncio.Queue() for site in url_parsers.keys()}
        # Separate queue for delayed retry processing (Hail-Mary protocol)
        waiting_queue = asyncio.Queue()
        
        # Initialize Calibre database interface (no longer needs mp.Manager)
        cdb_info = calibre_info.CalibreInfo(args.config, manager=None)
        cdb_info.check_installed()

        # Register email watcher task for URL ingestion
        task_manager.register_task(
            "email_watcher",
            url_ingester.email_watcher,
            email_info,
            notification_info,
            queues,
            url_parsers,
        )

        # Register waiting watcher task for retry handling
        task_manager.register_task(
            "waiting_watcher",
            ff_waiter.wait_processor,
            queues,
            waiting_queue,
        )

        # Register URL worker tasks for each supported fanfiction site
        for site in queues.keys():
            task_manager.register_task(
                f"worker_{site}",
                url_worker.url_worker,
                queues[site],
                cdb_info,
                notification_info,
                waiting_queue,
                config.retry,
            )

        # Start all tasks with monitoring and graceful shutdown capability
        ff_logging.log("Starting all tasks...")
        await task_manager.start_all()
        ff_logging.log("All tasks started successfully")

        # The TaskManager context manager will handle graceful shutdown
        ff_logging.log("Tasks running. Press Ctrl+C to stop gracefully.")

        # Keep the main task alive while worker tasks run continuously
        try:
            # Wait for tasks to complete (they run indefinitely until stopped)
            # The TaskManager signal handlers will handle SIGTERM/SIGINT and
            # cause wait_for_all() to exit promptly via the shutdown event
            await task_manager.wait_for_all()  # Wait indefinitely for normal completion
            ff_logging.log("All tasks completed normally")

        except KeyboardInterrupt:
            # KeyboardInterrupt (Ctrl+C) generates SIGINT, which should be handled
            # by TaskManager's signal handlers. However, if we reach this point,
            # it means the signal handler didn't handle it properly or there's a race condition.
            ff_logging.log(
                "KeyboardInterrupt caught - signal handler may not have handled shutdown",
                "WARNING",
            )

            # Check if shutdown is already in progress to avoid duplicate cleanup
            if not task_manager._shutdown_event.is_set():
                ff_logging.log(
                    "Initiating manual shutdown due to KeyboardInterrupt"
                )
                await task_manager.stop_all()

            # Brief wait for tasks to complete after manual shutdown
            # Timeout prevents indefinite hanging on stuck tasks
            if not await task_manager.wait_for_all(timeout=30.0):
                ff_logging.log_failure(
                    "Timeout waiting for tasks after manual shutdown"
                )
            else:
                ff_logging.log("Manual shutdown completed successfully")

    ff_logging.log("Application shutdown complete")


def main() -> None:
    """Synchronous wrapper for the async main function.
    
    This function sets up the asyncio event loop and runs the async_main coroutine.
    It's the actual entry point called when the script is executed.
    """
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        # asyncio.run handles cleanup, just exit gracefully
        ff_logging.log("Application interrupted by user")
    except Exception as e:
        ff_logging.log_failure(f"Unexpected error in main: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
