"""Shared application state for FastAPI dependency injection.

WebState holds references to all shared multiprocessing objects and config,
injected into route handlers via FastAPI's Depends() mechanism.
"""

import multiprocessing as mp
from dataclasses import dataclass
from typing import Any

from history.database import AsyncHistoryDB


@dataclass
class WebState:
    """Container for all shared state accessible by web route handlers.

    Created once in run_web_server() and attached to the FastAPI app instance.
    Route handlers access it via get_state() dependency.
    """

    # History database (async reads)
    history_db: AsyncHistoryDB | None = None

    # Shared multiprocessing objects (read-only from web server)
    active_urls: dict | None = None
    ingress_queue: mp.Queue | None = None
    worker_queues: dict | None = None
    waiting_queue: mp.Queue | None = None

    # Process manager reference for status queries
    process_status_callable: Any | None = None

    # History recorder (queue-based, for writes from web routes)
    history_recorder: Any | None = None

    # Configuration
    config: Any | None = None
    config_path: str | None = None
    config_store: Any | None = None  # ConfigStore for hot-reload

    # Web server auto-restart event (set by config route when web.* fields change)
    web_restart_event: Any | None = None

    # Verbose flag
    verbose: bool = False
