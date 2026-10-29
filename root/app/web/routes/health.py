"""Health and status API routes."""

from fastapi import APIRouter, Request

lazy from calibre_integration import calibredb_utils, factory as calibre_factory
lazy from fanficdownload import __version__
from utils import system_utils
lazy from workers import fff_runner

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}


@router.get("/version")
async def system_version(request: Request) -> dict[str, object]:
    """Return runtime environment and component versions for diagnostics and error reporting."""
    state = request.app.state.web_state
    calibre_ver = "unknown"
    if getattr(state, "config", None) and getattr(state.config, "calibre", None):
        try:
            client = getattr(request.app.state, "calibre_client", None)
            if client and hasattr(client, "get_version"):
                calibre_ver = client.get_version()
            elif not calibre_factory.is_http_location(
                getattr(state.config.calibre, "path", "")
            ):
                calibre_ver = calibredb_utils.CalibreDBClient.get_calibre_version()
        except Exception:
            pass

    env = system_utils.get_system_environment_summary()
    fff_ver = fff_runner.get_fanficfare_version()
    apprise_ver = system_utils.get_installed_package_version("apprise")

    return {
        "automatedfanfic": __version__,
        "python": str(env["python"]),
        "python_implementation": str(env["python_implementation"]),
        "platform": str(env["platform"]),
        "os": str(env["os"]),
        "arch": str(env["arch"]),
        "is_docker": bool(env["is_docker"]),
        "calibre": calibre_ver,
        "fanficfare": fff_ver,
        "apprise": apprise_ver,
    }


@router.get("/status")
async def system_status(request: Request):
    """Overall system status including process states and queue sizes."""
    state = request.app.state.web_state

    queues: dict[str, object] = {}
    result: dict[str, object] = {
        "status": "running",
        "version": __version__,
        "processes": {},
        "queues": queues,
    }

    # Process status
    if state.process_status_callable:
        try:
            result["processes"] = state.process_status_callable()
        except Exception:
            result["processes"] = {"error": "unavailable"}

    # Queue sizes (qsize may not be supported on all platforms)
    for name, queue in [
        ("ingress", state.ingress_queue),
        ("waiting", state.waiting_queue),
    ]:
        if queue is not None:
            try:
                queues[name] = queue.qsize()
            except NotImplementedError:
                queues[name] = -1

    if state.worker_queues:
        workers_dict: dict[str, int] = {}
        queues["workers"] = workers_dict
        for worker_id, queue in state.worker_queues.items():
            try:
                workers_dict[worker_id] = queue.qsize()
            except NotImplementedError:
                workers_dict[worker_id] = -1

    # Active downloads count
    if state.active_urls is not None:
        try:
            result["active_downloads"] = len(state.active_urls)
        except Exception:
            result["active_downloads"] = -1

    return result
