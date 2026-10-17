"""
Context dataclasses for bundling worker and cross-process dependencies.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from calibre_integration import calibre_info, calibredb_utils
    from models import config_models
    from models.queue_types import IngressQueue, LogQueue, WaitingQueue, WorkerQueues
    from notifications import notification_wrapper


@dataclass
class WorkerContext:
    """Bundles shared dependencies for worker threads and task handlers."""

    calibre_client: calibredb_utils.CalibreDBClient
    notification_info: notification_wrapper.NotificationWrapper
    ingress_queue: IngressQueue
    waiting_queue: WaitingQueue
    retry_config: config_models.RetryConfig
    history_recorder: Any | None = None
    active_urls: MutableMapping[str, Any] | None = None

    @property
    def cdb_info(self) -> calibre_info.CalibreInfo | None:
        """Convenience accessor for CalibreInfo from calibre_client."""
        return self.calibre_client.cdb_info if self.calibre_client is not None else None


@dataclass
class SharedIPCContext:
    """Picklable container for cross-process queues and shared state."""

    ingress_queue: IngressQueue
    waiting_queue: WaitingQueue
    worker_queues: WorkerQueues
    active_urls: MutableMapping[str, Any]
    history_recorder: Any | None = None
    config_store: Any | None = None
    log_queue: LogQueue | None = None
    verbose: bool = False
