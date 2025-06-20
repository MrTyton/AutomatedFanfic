import argparse
import multiprocessing as mp
import signal
import sys
import tomllib
import ff_logging  # Custom logging module for formatted logging

import calibre_info
import ff_waiter
import notification_wrapper
import regex_parsing
import url_ingester
import url_worker

# Define the application version
__version__ = "1.3.11"


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


def create_processes(
    email_info: url_ingester.EmailInfo,
    notification_info: notification_wrapper.NotificationWrapper,
    queues: dict[str, mp.Queue],
    waiting_queue: mp.Queue,
    cdb_info: calibre_info.CalibreInfo,
) -> tuple[mp.Process, mp.Process]:
    """
    Initializes and returns two multiprocessing processes: one for monitoring
    emails and another for processing items in the waiting queue.

    This function sets up two separate processes. The first process,
    `email_watcher`, is responsible for continuously monitoring an email inbox for
    new messages that contain URLs to be downloaded. The second process,
    `waiting_watcher`, processes items that have been placed into a waiting queue,
    typically because they require some form of delayed processing or are awaiting
    certain conditions to be met.

    Args:
        email_info (url_ingester.EmailInfo): Configuration and information
            necessary for the email monitoring process, including login credentials
            and server details.
        pushbullet_info (pushbullet_notification.PushbulletNotification):
            Configuration for Pushbullet notifications, used to send alerts or
            updates related to the email monitoring and URL downloading process.
        queues (dict[str, mp.Queue]): A dictionary mapping site names to
            multiprocessing queues. These queues are used to distribute URLs to
            specific site handlers for downloading.
        waiting_queue (mp.Queue): A multiprocessing queue that holds items awaiting
            processing. Items in this queue are typically URLs that could not be
            immediately downloaded and require further attention.
        cdb_info (calibre_info.CalibreInfo): Information and operations related to a
            Calibre database, which may be used for cataloging and storing
            downloaded content.

    Returns:
        tuple[mp.Process, mp.Process]: A tuple containing the initialized
            `email_watcher` and `waiting_watcher` processes, ready to be started.
    """
    email_watcher = mp.Process(
        target=url_ingester.email_watcher,
        args=(email_info, notification_info, queues),
    )
    waiting_watcher = mp.Process(
        target=ff_waiter.wait_processor, args=(queues, waiting_queue)
    )
    return email_watcher, waiting_watcher


def start_processes(processes):
    """
    Starts the given list of multiprocessing processes.

    Args:
        processes (list): A list of multiprocessing.Process objects to be started.
    """
    for process in processes:
        process.start()


def join_processes(processes):
    """
    Joins the given list of multiprocessing processes. This blocks the calling
    thread until processes terminate.

    Args:
        processes (list): A list of multiprocessing.Process objects to be joined.
    """
    for process in processes:
        process.join()


def terminate_processes(processes):
    """
    Terminates the given list of multiprocessing processes.

    Args:
        processes (list): A list of multiprocessing.Process objects to be terminated.
    """
    for process in processes:
        process.terminate()


def signal_handler(processes, pool):
    """
    Creates a signal handler for gracefully terminating processes and pool.

    Args:
        processes (list): A list of multiprocessing.Process objects to be terminated
            upon receiving a signal.
        pool (mp.Pool): A multiprocessing pool to be terminated upon receiving a
            signal.

    Returns:
        function: A handler function to be used with signal.signal().
    """

    def handler(sig, frame):
        ff_logging.log_failure("Terminating processes and pool...")
        terminate_processes(processes)
        if pool is not None:
            pool.terminate()
        sys.exit(0)

    return handler


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

    try:
        with open(args.config, "rb") as fp:
            config_data = tomllib.load(fp)
    except FileNotFoundError:
        ff_logging.log_failure(f"Configuration file not found at {args.config}")
        sys.exit(1)
    except Exception as e:
        ff_logging.log_failure(f"Error loading configuration file {args.config}: {e}")
        sys.exit(1)

    # --- Log Specific Configuration Details ---
    # Initialize NotificationWrapper early for logging
    notification_info = notification_wrapper.NotificationWrapper(toml_path=args.config)

    ff_logging.log("--- Configuration Details ---")
    try:
        # Log Email Address
        email_address = config_data.get("email", {}).get("email", "Not Specified")
        ff_logging.log(f"  Email Account: {email_address}")
        email_server = config_data.get("email", {}).get("server", "Not Specified")
        ff_logging.log(f"  Email Server: {email_server}")
        email_mailbox = config_data.get("email", {}).get("mailbox", "Not Specified")
        ff_logging.log(f"  Email Mailbox: {email_mailbox}")
        email_sleep_time = config_data.get("email", {}).get(
            "sleep_time", 60
        )  # Default to 60 if not specified
        ff_logging.log(f"  Email Sleep Time: {email_sleep_time}")
        email_ffnet_disable = config_data.get("email", {}).get(
            "ffnet_disable", True
        )  # Default to True
        ff_logging.log(f"  FFNet Disabled: {email_ffnet_disable}")

        # Log Calibre Path
        calibre_path = config_data.get("calibre", {}).get("path", "Not Specified")
        ff_logging.log(f"  Calibre Path: {calibre_path}")
        calibre_default_ini = config_data.get("calibre", {}).get(
            "default_ini", "Not Specified"
        )
        ff_logging.log(f"  Calibre Default INI: {calibre_default_ini}")
        calibre_personal_ini = config_data.get("calibre", {}).get(
            "personal_ini", "Not Specified"
        )
        ff_logging.log(f"  Calibre Personal INI: {calibre_personal_ini}")

        # Log Pushbullet Status
        pb_enabled = config_data.get("pushbullet", {}).get("enabled", False)
        pb_status = "Enabled" if pb_enabled else "Disabled"
        ff_logging.log(f"  Pushbullet Notifications: {pb_status}")
        if pb_enabled:
            pb_device = config_data.get("pushbullet", {}).get("device", "Not Specified")
            ff_logging.log(f"  Pushbullet Device: {pb_device}")

        # Log Apprise Status
        apprise_urls = config_data.get("apprise", {}).get("urls", [])
        if apprise_urls:
            ff_logging.log(
                f"  Apprise Notifications: Enabled with {len(apprise_urls)} target(s)"
            )
        else:
            ff_logging.log("  Apprise Notifications: Disabled")

    except Exception as e:
        ff_logging.log_failure(f"  Error accessing specific configuration details: {e}")
    ff_logging.log("-----------------------------")
    # --- End Logging ---

    # Initialize configurations for email
    email_info = url_ingester.EmailInfo(args.config)

    with mp.Manager() as manager:
        # Create queues for each site and a waiting queue for delayed processing
        queues = {site: manager.Queue() for site in regex_parsing.url_parsers.keys()}
        waiting_queue = manager.Queue()
        cdb_info = calibre_info.CalibreInfo(args.config, manager)
        cdb_info.check_installed()

        # Create and start email watcher and waiting watcher processes
        email_watcher, waiting_watcher = create_processes(
            email_info, notification_info, queues, waiting_queue, cdb_info
        )
        processes = [email_watcher, waiting_watcher]
        signal.signal(signal.SIGTERM, signal_handler(processes, None))
        start_processes(processes)

        # Create worker tasks for processing URLs from each site
        workers = [
            (queues[site], cdb_info, notification_info, waiting_queue)
            for site in queues.keys()
        ]
        with mp.Pool(len(queues)) as pool:
            # Reassign signal handler to include pool termination
            signal.signal(signal.SIGTERM, signal_handler(processes, pool))
            pool.starmap(url_worker.url_worker, workers)

        join_processes(processes)


if __name__ == "__main__":
    main()
