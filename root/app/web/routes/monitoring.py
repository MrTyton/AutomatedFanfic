"""Monitoring API routes — active downloads, workers, queue depths."""

from fastapi import APIRouter, Request

from models import active_urls as active_urls_utils

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/active")
async def active_downloads(request: Request):
    """List of URLs currently being processed with metadata."""
    state = request.app.state.web_state
    if state.active_urls is None:
        return {"items": [], "count": 0}

    try:
        items = [
            {"url": url, **(meta if isinstance(meta, dict) else {})}
            for url, meta in state.active_urls.items()
            if not (isinstance(meta, dict) and meta.get("status") == "cancelled")
        ]
    except Exception:
        items = []

    return {"items": items, "count": len(items)}


@router.get("/queues")
async def queue_depths(request: Request):
    """Current queue sizes across the system."""
    state = request.app.state.web_state
    return active_urls_utils.get_queue_depths(
        state.ingress_queue, state.waiting_queue, state.worker_queues
    )


@router.get("/workers")
async def worker_status(request: Request):
    """Worker process and thread status."""
    state = request.app.state.web_state
    result = {"workers": {}}

    if state.process_status_callable:
        try:
            all_status = state.process_status_callable()
            # Filter for worker-related entries
            for name, info in all_status.items():
                if "worker" in name.lower():
                    result["workers"][name] = info
        except Exception:
            pass

    return result
