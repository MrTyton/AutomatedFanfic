"""
Supervisor Service for AutomatedFanfic

This module implements a process supervisor that hosts lightweight helper services
(Email Watcher, Waiter, Coordinator) as threads within a single process.
This significantly reduces memory usage by sharing the Python interpreter instance
while maintaining isolation from the main process.
"""

import threading
import signal
import time
import multiprocessing as mp
from typing import Dict, Any

from utils import ff_logging
from services import url_ingester, ff_waiter, coordinator


def run_supervisor(
    worker_queues: Dict[str, mp.Queue],
    ingress_queue: mp.Queue,
    waiting_queue: mp.Queue,
    email_info: url_ingester.EmailInfo,
    notification_info: Any,
    url_parsers: Dict,
    active_urls: Dict,
    verbose: bool = False,
):
    """
    Entry point for the Supervisor process.

    Hosts the following services as threads:
    - Email Watcher
    - Fanfic Waiter
    - Coordinator
    """
    # Initialize logging for this process
    ff_logging.set_verbose(verbose)
    ff_logging.set_thread_color("\033[92m")  # Green for Supervisor

    shutdown_event = threading.Event()
    threads = []

    # helper for signal handling
    def signal_handler(signum, frame):
        ff_logging.log_debug(
            f"Supervisor received signal {signum}, shutting down threads..."
        )
        shutdown_event.set()

    # Register signal handlers for graceful shutdown (SIGTERM from ProcessManager)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        ff_logging.log("Supervisor: Starting helper services...")

        # 1. Email Watcher Thread
        email_thread = threading.Thread(
            target=url_ingester.email_watcher,
            args=(
                email_info,
                notification_info,
                ingress_queue,
                url_parsers,
                active_urls,
                verbose,
                shutdown_event,
            ),
            name="EmailWatcher",
        )
        threads.append(email_thread)

        # 2. Waiter Thread
        waiter_thread = threading.Thread(
            target=ff_waiter.wait_processor,
            args=(ingress_queue, waiting_queue, verbose, shutdown_event),
            name="Waiter",
        )
        threads.append(waiter_thread)

        # 3. Coordinator Thread
        coord_thread = threading.Thread(
            target=coordinator.start_coordinator,
            args=(ingress_queue, worker_queues, verbose, shutdown_event),
            name="Coordinator",
        )
        threads.append(coord_thread)

        # Start all threads
        for t in threads:
            t.start()
            ff_logging.log_debug(f"Supervisor: Started {t.name}")

        # Keep the main thread alive until shutdown
        while not shutdown_event.is_set():
            # Check if any critical thread has died unexpectedly
            for t in threads:
                if not t.is_alive():
                    ff_logging.log_failure(
                        f"Supervisor: Critical thread {t.name} died! Shutting down supervisor to trigger restart."
                    )
                    shutdown_event.set()
                    break

            if not shutdown_event.is_set():
                time.sleep(1.0)  # Check every second

    except Exception as e:
        ff_logging.log_failure(f"Supervisor: Error in main loop: {e}")
        shutdown_event.set()
    finally:
        ff_logging.log("Supervisor: Waiting for threads to stop...")
        for t in threads:
            if t.is_alive():
                t.join(timeout=5.0)
                if t.is_alive():
                    ff_logging.log(
                        f"Supervisor: Thread {t.name} did not stop gracefully",
                        "WARNING",
                    )

        ff_logging.log("Supervisor: Shutdown complete")
