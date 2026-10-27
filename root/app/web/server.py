"""FastAPI web server for the AutomatedFanfic dashboard.

Provides:
- create_app(): Factory that builds and configures the FastAPI application.
- run_web_server(): Process entry point compatible with ProcessManager.register_process().
"""

import signal
from collections.abc import Callable
from contextlib import asynccontextmanager
from multiprocessing.synchronize import Event
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from models.config_models import AppConfig, ConfigManager
from history.database import AsyncHistoryDB
from models.context import SharedIPCContext
from utils import ff_logging
from web.dependencies import WebState
from web.routes import (
    config,
    controls,
    health,
    history,
    logs,
    monitoring,
    stats,
    websocket,
    widget,
)
lazy from web.routes import debug


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Manage async resources (history DB connection) on startup/shutdown."""
    state: WebState = app.state.web_state

    # Connect async history DB if configured
    if state.history_db is not None:
        if hasattr(state.history_db, "connect"):
            await state.history_db.connect()
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

    # Compress large JSON responses (e.g. /api/logs, /api/config/fff, /api/stats)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

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
    app.include_router(logs.router)
    app.include_router(monitoring.router)
    app.include_router(controls.router)
    app.include_router(config.router)
    app.include_router(websocket.router)
    app.include_router(widget.router)
    app.include_router(stats.router)
    app.include_router(debug.router)

    # Serve React SPA static files (must come after API routes)
    _static_dir = Path(__file__).resolve().parent.parent.parent / "web-ui" / "dist"
    if _static_dir.is_dir():
        app.mount(
            "/assets", StaticFiles(directory=_static_dir / "assets"), name="assets"
        )

        @app.get("/{full_path:path}")
        async def _spa_fallback(full_path: str):
            """Serve index.html for all non-API paths (SPA client-side routing)."""
            if full_path.startswith(("api/", "ws/")):
                return JSONResponse(
                    status_code=404,
                    content={"detail": f"API route not found: /{full_path}"},
                )
            return FileResponse(_static_dir / "index.html")

    return app


def run_web_server(
    ipc: SharedIPCContext,
    app_config: AppConfig,
    config_path: str,
    web_restart_event: Event,
    process_status_callable: Callable[[], dict[str, object]] | None = None,
) -> None:
    """Process entry point for the web server.

    Compatible with `ProcessManager.register_process()`. Runs uvicorn in the
    subprocess with signal handling for graceful shutdown.

    Args:
        ipc (SharedIPCContext): Shared multiprocessing queues, active_urls,
            history_recorder, config_store, log_queue, and verbosity flag.
        app_config (AppConfig): Validated application configuration object.
        config_path (str): Path to the TOML configuration file for persisting
            configuration edits made through the web UI.
        web_restart_event (Event): Shared event set when `web.host` or
            `web.port` changes require a web server restart.
        process_status_callable (Callable[[], dict[str, Any]] | None, optional):
            Optional callable returning process health status dictionary.
    """
    ff_logging.init_process_logging(
        ipc.verbose,
        color="\033[95m",  # Magenta for web server
        log_queue=ipc.log_queue,
        config_store=ipc.config_store,
        is_web_server=True,
    )

    shutdown_event = ipc.shutdown_event

    def signal_handler(signum, frame):
        ff_logging.log_debug(f"WebServer received signal {signum}, shutting down...")
        shutdown_event.set()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    web_cfg = getattr(app_config, "web", None)
    host = getattr(web_cfg, "host", "0.0.0.0") or "0.0.0.0"
    port = int(getattr(web_cfg, "port", 8080) or 8080)
    history_db_path = getattr(web_cfg, "history_db_path", None)

    # Build shared state
    web_state = WebState(
        history_db=AsyncHistoryDB(history_db_path) if history_db_path else None,
        active_urls=ipc.active_urls,
        ingress_queue=ipc.ingress_queue,
        worker_queues=ipc.worker_queues,
        waiting_queue=ipc.waiting_queue,
        process_status_callable=process_status_callable,
        history_recorder=ipc.history_recorder,
        config=app_config,
        config_path=config_path,
        config_store=ipc.config_store,
        web_restart_event=web_restart_event,
        check_emails_event=ipc.check_emails_event,
        verbose=ipc.verbose,
        coordinator_status=ipc.coordinator_status,
    )

    app = create_app(web_state)

    ff_logging.log(f"WebServer: Starting on {host}:{port}")

    # Re-read host/port from TOML — picks up new values after a config-driven
    # restart without needing to pass them explicitly through ProcessManager.
    if config_path:
        try:
            fresh = ConfigManager.load_config(config_path)
            host = fresh.web.host
            port = fresh.web.port
            ff_logging.log_debug(
                f"WebServer: using config-file host={host} port={port}"
            )
        except Exception:
            pass  # Fall back to the originally passed-in values

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
