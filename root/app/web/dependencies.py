"""Shared application state for FastAPI dependency injection.

WebState holds references to all shared multiprocessing objects and config,
injected into route handlers via FastAPI's Depends() mechanism.
"""

from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.synchronize import Event

from config.config_store import ConfigStore
from history.database import AsyncHistoryDB
from history.recorder import HistoryRecorder
from models.active_urls import ActiveUrlsDict
from models.config_models import AppConfig
from models.queue_types import (
    CheckEmailsEvent,
    IngressQueue,
    WaitingQueue,
    WorkerQueues,
)


@dataclass
class WebState:
    """Container for all shared state accessible by web route handlers.

    Created once in run_web_server() and attached to the FastAPI app instance.
    Route handlers access it via get_state() dependency.
    """

    # History database (async reads)
    history_db: AsyncHistoryDB | None = None

    # Shared multiprocessing objects (read-only from web server)
    active_urls: ActiveUrlsDict | None = None
    ingress_queue: IngressQueue | None = None
    worker_queues: WorkerQueues | None = None
    waiting_queue: WaitingQueue | None = None

    # Process manager reference for status queries
    process_status_callable: Callable[[], dict[str, object]] | None = None

    # History recorder (queue-based, for writes from web routes)
    history_recorder: HistoryRecorder | None = None

    # Configuration
    config: AppConfig | None = None
    config_path: str | None = None
    config_store: ConfigStore | None = None  # ConfigStore for hot-reload

    # Web server auto-restart event (set by config route when web.* fields change)
    web_restart_event: Event | None = None

    # Manual email check trigger event (set by controls route to wake EmailWatcher)
    check_emails_event: CheckEmailsEvent | None = None

    # Verbose flag
    verbose: bool = False
