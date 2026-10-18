"""
Context dataclasses for bundling worker and cross-process dependencies.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from calibre_integration import calibre_info, calibredb_utils
    from config.config_store import ConfigStore
    from history.recorder import HistoryRecorder
    from models import config_models
    from models.queue_types import (
        IngressQueue,
        LogQueue,
        ScaleQueue,
        WaitingQueue,
        WorkerQueues,
    )
    from notifications import notification_wrapper


@dataclass
class WorkerContext:
    """Bundles shared dependencies for worker threads and task handlers.

    Attributes:
        calibre_client (CalibreDBClient): Client for executing calibredb operations.
        notification_info (NotificationWrapper): Coordinator for dispatching notifications.
        ingress_queue (IngressQueue): Unified task ingress queue for idle signals and force retries.
        waiting_queue (WaitingQueue): Queue for failed tasks awaiting delayed retry.
        retry_config (RetryConfig): Configuration governing retry counts and Hail-Mary backoff.
        history_recorder (HistoryRecorder): Recorder for persisting history events.
        active_urls (MutableMapping[str, Any]): Shared map of active URLs.
    """

    calibre_client: calibredb_utils.CalibreDBClient
    notification_info: notification_wrapper.NotificationWrapper
    ingress_queue: IngressQueue
    waiting_queue: WaitingQueue
    retry_config: config_models.RetryConfig
    history_recorder: HistoryRecorder
    active_urls: MutableMapping[str, Any]

    @property
    def cdb_info(self) -> calibre_info.CalibreInfo:
        """Convenience accessor for CalibreInfo from `calibre_client`.

        Returns:
            CalibreInfo: The underlying CalibreInfo instance.
        """
        return self.calibre_client.cdb_info


@dataclass
class SharedIPCContext:
    """Picklable container for cross-process queues and shared state.

    Passed from the main process to child processes (`supervisor`, `worker_pool`,
    and `web_server`) to avoid passing 8+ positional multiprocessing arguments.

    Attributes:
        ingress_queue (IngressQueue): Unified task and worker signal ingress queue.
        waiting_queue (WaitingQueue): Delayed retry queue consumed by `ff_waiter`.
        worker_queues (WorkerQueues): Shared dict mapping `worker_id` to worker queues.
        active_urls (MutableMapping[str, Any]): Shared dict tracking in-flight URLs.
        history_recorder (HistoryRecorder): Shared history event recorder.
        config_store (ConfigStore): Shared ConfigStore for runtime hot-reloading.
        log_queue (LogQueue | None): Optional queue for forwarding logs to the web server.
        verbose (bool): Whether verbose debug logging is enabled across processes.
        scale_queue (ScaleQueue | None): Optional queue for notifying worker pool of scaling requests.
    """

    ingress_queue: IngressQueue
    waiting_queue: WaitingQueue
    worker_queues: WorkerQueues
    active_urls: MutableMapping[str, Any]
    history_recorder: HistoryRecorder
    config_store: ConfigStore
    log_queue: LogQueue | None = None
    verbose: bool = False
    scale_queue: ScaleQueue | None = None
