"""
Worker Pool Runner for AutomatedFanfic

This module implements a process-isolated thread pool for running worker instances.
It serves as a container process that spawns multiple threads to handle fanfiction
downloads, significantly reducing memory overhead compared to multi-process approaches.
"""

import threading
import signal
from queue import Empty

from utils import ff_logging
from workers import pipeline
from models import config_models
from models.context import SharedIPCContext, WorkerContext
from models.queue_types import WorkerQueue
from calibre_integration import calibredb_utils
from notifications import notification_wrapper

DEFAULT_BURST_IDLE_TIMEOUT: float = 60.0


def _spawn_worker_thread(
    worker_id: str,
    queue: WorkerQueue,
    ctx: WorkerContext,
    verbose: bool,
    idle_timeout: float | None = None,
) -> threading.Thread:
    """Create and start a daemon worker thread running `pipeline.url_worker`.

    Args:
        worker_id (str): Unique identifier for the worker thread (e.g., 'worker_0').
        queue (WorkerQueue): Dedicated task queue assigned to this worker.
        ctx (WorkerContext): Shared worker dependencies (Calibre client, notifications,
            queues, retry config, history recorder, and active_urls).
        verbose (bool): Whether verbose debug logging is enabled.
        idle_timeout (float | None, optional): Maximum idle duration in seconds
            before terminating the worker thread. Defaults to None (runs indefinitely).

    Returns:
        threading.Thread: The started daemon thread instance.
    """
    thread = threading.Thread(
        target=pipeline.url_worker,
        args=(queue, ctx, worker_id, verbose, idle_timeout),
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
    scale_queue = ipc.scale_queue

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

    active_threads: dict[str, threading.Thread] = {}
    shutdown_event = ipc.shutdown_event

    # Define signal handler for graceful shutdown of the pool process
    def signal_handler(signum, frame):
        ff_logging.log_debug("Worker Pool received shutdown signal")
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Initial spawn logic
        if "worker_0" in worker_queues:
            active_threads["worker_0"] = _spawn_worker_thread(
                "worker_0",
                worker_queues["worker_0"],
                worker_ctx,
                verbose,
                idle_timeout=None,
            )
        else:
            for worker_id, queue in worker_queues.items():
                active_threads[worker_id] = _spawn_worker_thread(
                    worker_id,
                    queue,
                    worker_ctx,
                    verbose,
                    idle_timeout=None,
                )

        # Main loop: Wait for shutdown and periodically check scale_queue and thread health
        while not shutdown_event.is_set():
            try:
                target_worker = scale_queue.get(timeout=0.2)
                while target_worker:
                    if target_worker in worker_queues:
                        existing_thread = active_threads.get(target_worker)
                        if existing_thread is not None and existing_thread.is_alive():
                            # The coordinator only signals scale_queue for workers that reported WORKER_STOPPED.
                            # Wait briefly for the dying thread to complete its exit/cleanup.
                            existing_thread.join(timeout=1.0)

                        if (
                            target_worker not in active_threads
                            or not active_threads[target_worker].is_alive()
                        ):
                            ff_logging.log(
                                f"Worker Pool: spawning thread for {target_worker}"
                            )
                            active_threads[target_worker] = _spawn_worker_thread(
                                target_worker,
                                worker_queues[target_worker],
                                worker_ctx,
                                verbose,
                                idle_timeout=DEFAULT_BURST_IDLE_TIMEOUT,
                            )
                    try:
                        target_worker = scale_queue.get_nowait()
                    except Empty:
                        break
            except Empty:
                pass
            except OSError, ValueError:
                ff_logging.log_debug("Worker Pool: scale_queue closed")
                break

            # Thread health check
            for worker_id in list(active_threads.keys()):
                t = active_threads[worker_id]
                if not t.is_alive():
                    if worker_id == "worker_0" or (
                        "worker_0" not in worker_queues and worker_id in worker_queues
                    ):
                        ff_logging.log_failure(
                            f"Thread {worker_id} died unexpectedly - Restarting..."
                        )
                        active_threads[worker_id] = _spawn_worker_thread(
                            worker_id,
                            worker_queues[worker_id],
                            worker_ctx,
                            verbose,
                            idle_timeout=None,
                        )
                    else:
                        ff_logging.log_debug(
                            f"Thread {worker_id} stopped (idle timeout or finished)"
                        )
                        del active_threads[worker_id]

    except KeyboardInterrupt:
        ff_logging.log("Worker Pool interrupted", "WARNING")
    finally:
        ff_logging.log_debug("Worker Pool shutting down threads...")
        pass
