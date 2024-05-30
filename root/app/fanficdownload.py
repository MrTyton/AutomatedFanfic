import argparse
import multiprocessing as mp
import signal
import sys

import calibre_info
import ff_waiter
import pushbullet_notification
import regex_parsing
import url_ingester
import url_worker

if __name__ == "__main__":
    # Create an argument parser
    parser = argparse.ArgumentParser(description="Process input arguments.")
    parser.add_argument(
        "--config", default="../config.default/config.toml", help="The location of the config.toml file"
    )

    # Parse the command line arguments
    args = parser.parse_args()

    # Initialize CalibreInfo, EmailInfo, and PushbulletNotification objects
    email_info = url_ingester.EmailInfo(args.config)
    pushbullet_info = pushbullet_notification.PushbulletNotification(args.config)

    with mp.Manager() as manager:
        # Create a dictionary of multiprocessing queues for each URL parser
        queues = {site: manager.Queue() for site in regex_parsing.url_parsers.keys()}
        waiting_queue = manager.Queue()

        cdb_info = calibre_info.CalibreInfo(args.config, manager)

        # Check if Calibre is installed
        cdb_info.check_installed()

        def signal_handler(sig, frame):
            """Handle received signals and terminate the program."""
            email_watcher.terminate()  # Terminate the email watcher process
            waiting_watcher.terminate()  # Terminate the waiting watcher process
            pool.terminate()  # Terminate all worker processes in the pool
            sys.exit(0)  # Exit the program

        # Set the signal handler for SIGTERM
        signal.signal(signal.SIGTERM, signal_handler)

        # Start a new process to watch the email account for new URLs
        email_watcher = mp.Process(
            target=url_ingester.email_watcher, args=(email_info, pushbullet_info, queues)
        )
        email_watcher.start()

        waiting_watcher = mp.Process(
            target=ff_waiter.wait_processor, args=(queues, waiting_queue)
        )
        waiting_watcher.start()

        # Create a pool of worker processes to process URLs from the queues
        workers = [
            (queues[site], cdb_info, pushbullet_info, waiting_queue)
            for site in queues.keys()
        ]
        with mp.Pool(len(queues)) as pool:
            pool.starmap(url_worker.url_worker, workers)

        # Wait for the email watcher process to finish
        email_watcher.join()
        # Wait for the waiting watcher process to finish
        waiting_watcher.join()
