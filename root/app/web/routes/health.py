"""Health and status API routes."""

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}


@router.get("/status")
async def system_status(request: Request):
    """Overall system status including process states and queue sizes."""
    state = request.app.state.web_state

    queues: dict[str, object] = {}
    result: dict[str, object] = {"status": "running", "processes": {}, "queues": queues}

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
