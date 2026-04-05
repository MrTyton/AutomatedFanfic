"""Shared application state for FastAPI dependency injection.

WebState holds references to all shared multiprocessing objects and config,
injected into route handlers via FastAPI's Depends() mechanism.
"""

import multiprocessing as mp
from dataclasses import dataclass
from typing import Any, Optional

from history.database import AsyncHistoryDB


@dataclass
class WebState:
    """Container for all shared state accessible by web route handlers.

    Created once in run_web_server() and attached to the FastAPI app instance.
    Route handlers access it via get_state() dependency.
    """

    # History database (async reads)
    history_db: Optional[AsyncHistoryDB] = None

    # Shared multiprocessing objects (read-only from web server)
    active_urls: Optional[dict] = None
    ingress_queue: Optional[mp.Queue] = None
    worker_queues: Optional[dict] = None
    waiting_queue: Optional[mp.Queue] = None

    # Process manager reference for status queries
    process_status_callable: Optional[Any] = None

    # Configuration
    config: Optional[Any] = None
    config_path: Optional[str] = None
    config_store: Optional[Any] = None  # ConfigStore for hot-reload

    # Verbose flag
    verbose: bool = False
