"""
Worker Pool Runner for AutomatedFanfic

This module implements a process-isolated thread pool for running worker instances.
It serves as a container process that spawns multiple threads to handle fanfiction
downloads, significantly reducing memory overhead compared to multi-process approaches.
"""

import threading
import time
import signal

from utils import ff_logging
from workers import pipeline
from models import config_models
from models.context import SharedIPCContext, WorkerContext
from models.queue_types import WorkerQueue
from calibre_integration import calibredb_utils
from notifications import notification_wrapper


def _spawn_worker_thread(
    worker_id: str,
    queue: WorkerQueue,
    ctx: WorkerContext,
    verbose: bool,
) -> threading.Thread:
    """Create and start a daemon worker thread running `pipeline.url_worker`.

    Args:
        worker_id (str): Unique identifier for the worker thread (e.g., 'worker_0').
        queue (WorkerQueue): Dedicated task queue assigned to this worker.
        ctx (WorkerContext): Shared worker dependencies (Calibre client, notifications,
            queues, retry config, history recorder, and active_urls).
        verbose (bool): Whether verbose debug logging is enabled.

    Returns:
        threading.Thread: The started daemon thread instance.
    """
    thread = threading.Thread(
        target=pipeline.url_worker,
        args=(queue, ctx, worker_id, verbose),
        name=worker_id,
        daemon=True,
    )
    thread.start()
    return thread


def run_worker_pool(
    ipc: SharedIPCContext,
    calibre_client: calibredb_utils.CalibreDBClient,
    notification_info: notification_wrapper.NotificationWrapper,
    retry_config: config_models.RetryConfig,
) -> None:
    """
    Runs a pool of worker threads within a single process.

    Args:
        ipc: SharedIPCContext bundling queues, active_urls, history_recorder, config_store, log_queue, verbose.
        calibre_client: Shared Calibre client instance.
        notification_info: Shared notification wrapper.
        retry_config: Retry configuration.
    """
    worker_queues = ipc.worker_queues
    ingress_queue = ipc.ingress_queue
    waiting_queue = ipc.waiting_queue
    active_urls = ipc.active_urls
    verbose = ipc.verbose
    history_recorder = ipc.history_recorder
    config_store = ipc.config_store
    log_queue = ipc.log_queue

    # Initialize logging for this process
    ff_logging.init_process_logging(
        verbose,
        log_queue=log_queue,
        config_store=config_store,
        is_web_server=False,
    )

    # Attach ConfigStore so workers pick up credential changes at runtime
    if config_store is not None:
        calibre_client.set_config_store(config_store)
        notification_info.set_config_store(config_store)
        if hasattr(retry_config, "set_config_store"):
            retry_config.set_config_store(config_store)

    worker_ctx = WorkerContext(
        calibre_client=calibre_client,
        notification_info=notification_info,
        ingress_queue=ingress_queue,
        waiting_queue=waiting_queue,
        retry_config=retry_config,
        history_recorder=history_recorder,
        active_urls=active_urls,
    )

    ff_logging.log_debug(f"Worker Pool Process using {len(worker_queues)} threads")

    threads: list[threading.Thread] = []
    shutdown_event = threading.Event()

    # Define signal handler for graceful shutdown of the pool process
    def signal_handler(signum, frame):
        ff_logging.log_debug("Worker Pool received shutdown signal")
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Spawn threads for each worker queue
        for worker_id, queue in worker_queues.items():
            threads.append(_spawn_worker_thread(worker_id, queue, worker_ctx, verbose))

        # Main loop: Wait for shutdown and periodically check thread health / scale-up
        while not shutdown_event.is_set():
            time.sleep(2.0)

            # Check if any threads have died and restart them
            for i, t in enumerate(threads):
                if not t.is_alive():
                    worker_id = t.name
                    if worker_id in worker_queues:
                        ff_logging.log_failure(
                            f"Thread {worker_id} died unexpectedly - Restarting..."
                        )
                        threads[i] = _spawn_worker_thread(
                            worker_id,
                            worker_queues[worker_id],
                            worker_ctx,
                            verbose,
                        )
                    else:
                        ff_logging.log_debug(
                            f"Thread {worker_id} stopped (queue removed - intentional scale-down)"
                        )

            # Scale-up: spawn threads for any worker_queues entries not yet tracked
            tracked_ids = {t.name for t in threads}
            for worker_id in list(worker_queues.keys()):
                if worker_id not in tracked_ids:
                    ff_logging.log(f"Worker Pool: spawning new thread for {worker_id}")
                    threads.append(
                        _spawn_worker_thread(
                            worker_id,
                            worker_queues[worker_id],
                            worker_ctx,
                            verbose,
                        )
                    )
                    # Notify coordinator that this worker is now available
                    ingress_queue.put(("WORKER_IDLE", worker_id, None))

    except KeyboardInterrupt:
        ff_logging.log("Worker Pool interrupted", "WARNING")
    finally:
        ff_logging.log_debug("Worker Pool shutting down threads...")
        pass
