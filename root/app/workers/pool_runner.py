"""
Worker Pool Runner for AutomatedFanfic

This module implements a process-isolated thread pool for running worker instances.
It serves as a container process that spawns multiple threads to handle fanfiction
downloads, significantly reducing memory overhead compared to multi-process approaches.
"""

import threading
import multiprocessing as mp
import time
from typing import Dict, List
import signal

from utils import ff_logging
from workers import pipeline
from models import config_models
from calibre_integration import calibredb_utils
from notifications import notification_wrapper


def run_worker_pool(
    worker_queues: Dict[str, mp.Queue],
    calibre_client: calibredb_utils.CalibreDBClient,
    notification_info: notification_wrapper.NotificationWrapper,
    waiting_queue: mp.Queue,
    retry_config: config_models.RetryConfig,
    active_urls: dict,
    verbose: bool = False,
) -> None:
    """
    Runs a pool of worker threads within a single process.

    Args:
        worker_queues: Dictionary mapping worker_ids to their input queues.
        calibre_client: Shared Calibre client instance.
        notification_info: Shared notification wrapper.
        waiting_queue: Shared queue for retries (ingress queue).
        retry_config: Retry configuration.
        active_urls: Shared dictionary of active URLs.
        verbose: Verbose logging flag.
    """
    # Initialize logging for this process
    ff_logging.set_verbose(verbose)

    ff_logging.log_debug(f"Worker Pool Process using {len(worker_queues)} threads")

    threads: List[threading.Thread] = []
    shutdown_event = threading.Event()

    # Define signal handler for graceful shutdown of the pool process
    def signal_handler(signum, frame):
        ff_logging.log_debug("Worker Pool received shutdown signal")
        shutdown_event.set()
        # We don't need to do anything else, the threads are daemon threads
        # or we can wait for them. Ideally we wait.

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Spawn threads for each worker queue
        for worker_id, queue in worker_queues.items():
            t = threading.Thread(
                target=pipeline.url_worker,
                args=(
                    queue,
                    calibre_client,
                    notification_info,
                    waiting_queue,
                    retry_config,
                    worker_id,
                    active_urls,
                    verbose,
                ),
                name=worker_id,
                daemon=True,  # Important: Allows process to exit if threads are stuck
            )
            t.start()
            threads.append(t)

        # Main loop: Just wait for shutdown
        while not shutdown_event.is_set():
            time.sleep(0.5)

            # Check if any threads have died and restart them
            for i, t in enumerate(threads):
                if not t.is_alive():
                    worker_id = t.name
                    ff_logging.log_failure(
                        f"Thread {worker_id} died unexpectedly - Restarting..."
                    )

                    # Restart the worker thread
                    if worker_id in worker_queues:
                        new_thread = threading.Thread(
                            target=pipeline.url_worker,
                            args=(
                                worker_queues[worker_id],
                                calibre_client,
                                notification_info,
                                waiting_queue,
                                retry_config,
                                worker_id,
                                active_urls,
                                verbose,
                            ),
                            name=worker_id,
                            daemon=True,
                        )
                        new_thread.start()
                        threads[i] = new_thread  # Replace the dead thread
                    else:
                        ff_logging.log_failure(
                            f"Could not restart {worker_id}: Queue not found"
                        )

    except KeyboardInterrupt:
        ff_logging.log("Worker Pool interrupted", "WARNING")
    finally:
        ff_logging.log_debug("Worker Pool shutting down threads...")
        # Since threads are daemon, we can just exit.
        # But if we wanted clean shutdown, we'd need to signal them.
        # url_worker checks for None in queue, but we have 32 queues.
        # We'd need to put None in all of them.
        # Given they are mostly I/O bound on subprocess or sleep, daemon exit is safe enough
        # provided `process_manager` handles the heavy lifting of killing this process.
        pass
