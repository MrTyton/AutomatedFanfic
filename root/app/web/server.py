"""FastAPI web server for the AutomatedFanfic dashboard.

Provides:
- create_app(): Factory that builds and configures the FastAPI application.
- run_web_server(): Process entry point compatible with ProcessManager.register_process().
"""

import signal
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from history.database import AsyncHistoryDB
from utils import ff_logging
from web.dependencies import WebState
from web.routes import config, controls, health, history, monitoring, websocket


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Manage async resources (history DB connection) on startup/shutdown."""
    state: WebState = app.state.web_state

    # Connect async history DB if configured
    if state.history_db is not None:
        await state.history_db.ensure_schema()
        ff_logging.log("WebServer: History database connection established")

    yield

    # Cleanup
    if state.history_db is not None:
        await state.history_db.close()
        ff_logging.log("WebServer: History database connection closed")


def create_app(web_state: WebState) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        web_state: Shared state container with references to queues, config, etc.

    Returns:
        Configured FastAPI instance with all routes registered.
    """
    app = FastAPI(
        title="AutomatedFanfic Dashboard",
        description="Web interface for monitoring and controlling the fanfiction download system.",
        version="1.0.0",
        lifespan=_lifespan,
    )

    # Store shared state on app for access in route handlers
    app.state.web_state = web_state

    # CORS — allow all origins for local/Docker usage (no auth)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register route modules
    app.include_router(health.router)
    app.include_router(history.router)
    app.include_router(monitoring.router)
    app.include_router(controls.router)
    app.include_router(config.router)
    app.include_router(websocket.router)

    # Serve React SPA static files (must come after API routes)
    _static_dir = Path(__file__).resolve().parent.parent.parent / "web-ui" / "dist"
    if _static_dir.is_dir():
        app.mount(
            "/assets", StaticFiles(directory=_static_dir / "assets"), name="assets"
        )

        @app.get("/{full_path:path}")
        async def _spa_fallback(full_path: str):
            """Serve index.html for all non-API paths (SPA client-side routing)."""
            return FileResponse(_static_dir / "index.html")

    return app


def run_web_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    history_db_path: Optional[str] = None,
    active_urls: Optional[dict] = None,
    ingress_queue: Any = None,
    worker_queues: Optional[dict] = None,
    waiting_queue: Any = None,
    process_status_callable: Any = None,
    app_config: Any = None,
    config_path: Optional[str] = None,
    verbose: bool = False,
) -> None:
    """Process entry point for the web server.

    Compatible with ProcessManager.register_process(). Runs uvicorn in the
    subprocess with signal handling for graceful shutdown.
    """
    ff_logging.set_verbose(verbose)
    ff_logging.set_thread_color("\033[95m")  # Magenta for web server

    shutdown_event = threading.Event()

    def signal_handler(signum, frame):
        ff_logging.log_debug(f"WebServer received signal {signum}, shutting down...")
        shutdown_event.set()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Build shared state
    web_state = WebState(
        history_db=AsyncHistoryDB(history_db_path) if history_db_path else None,
        active_urls=active_urls,
        ingress_queue=ingress_queue,
        worker_queues=worker_queues,
        waiting_queue=waiting_queue,
        process_status_callable=process_status_callable,
        config=app_config,
        config_path=config_path,
        verbose=verbose,
    )

    app = create_app(web_state)

    ff_logging.log(f"WebServer: Starting on {host}:{port}")

    # Run uvicorn — it handles its own event loop
    uvicorn_config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(uvicorn_config)
    server.run()

    ff_logging.log("WebServer: Shutdown complete")
