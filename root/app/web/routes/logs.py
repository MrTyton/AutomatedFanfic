"""Log viewer API routes — retrieve recent application logs."""

from fastapi import APIRouter, Query

from utils import ff_logging

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def get_logs(limit: int = Query(default=500, ge=1, le=2000)):
    """Return recent log entries from the in-memory ring buffer.

    Newest entries are returned first.
    """
    entries = ff_logging.get_recent_logs(limit=limit)
    return {"items": entries, "count": len(entries)}


@router.get("/startup")
async def get_startup_logs(limit: int = Query(default=500, ge=1, le=2000)):
    """Return startup/initialization log entries from app boot."""
    entries = ff_logging.get_startup_logs(limit=limit)
    return {"items": entries, "count": len(entries)}
