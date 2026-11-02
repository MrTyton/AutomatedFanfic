"""Monitoring API routes — active downloads, workers, queue depths."""

from fastapi import APIRouter, Request

from models.active_urls import get_queue_depths
from web.services.dashboard_snapshot import (
    get_active_downloads_summary,
    get_worker_status_summary,
)

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/active")
async def active_downloads(request: Request):
    """List of URLs currently being processed with metadata."""
    return get_active_downloads_summary(request.app.state.web_state)


@router.get("/queues")
async def queue_depths(request: Request):
    """Current queue sizes across the system."""
    state = request.app.state.web_state
    return get_queue_depths(
        state.ingress_queue, state.waiting_queue, state.worker_queues
    )


@router.get("/workers")
async def worker_status(request: Request):
    """Worker process and thread status."""
    return get_worker_status_summary(request.app.state.web_state)
