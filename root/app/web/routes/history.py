"""History API routes — download events, retries, email checks, notifications."""

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/downloads")
async def list_downloads(
    request: Request,
    site: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int | None = Query(default=None, ge=0),
):
    """Paginated list of download events with optional filters."""
    db = request.app.state.web_state.history_db
    if db is None:
        return {"items": [], "total": 0}

    # Support both page/page_size and limit/offset params
    actual_limit = limit if limit is not None else page_size
    actual_offset = offset if offset is not None else (page - 1) * page_size

    items = await db.get_downloads(
        site=site, status=status, limit=actual_limit, offset=actual_offset
    )
    total = await db.get_download_count(site=site, status=status)
    return {"items": items, "total": total}


@router.get("/retries/{url:path}")
async def retries_for_url(request: Request, url: str):
    """All retry events for a specific URL, ordered by attempt number."""
    db = request.app.state.web_state.history_db
    if db is None:
        return {"items": []}

    items = await db.get_retries_for_url(url)
    return {"items": items}


@router.get("/emails")
async def list_email_checks(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Paginated list of email check events."""
    db = request.app.state.web_state.history_db
    if db is None:
        return {"items": []}

    items = await db.get_email_checks(limit=limit, offset=offset)
    return {"items": items}


@router.get("/notifications")
async def list_notifications(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Paginated list of notification events."""
    db = request.app.state.web_state.history_db
    if db is None:
        return {"items": []}

    items = await db.get_notifications(limit=limit, offset=offset)
    return {"items": items}


@router.get("/recent")
async def recent_events(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
):
    """Most recent events across all types (for dashboard feed)."""
    db = request.app.state.web_state.history_db
    if db is None:
        return {"items": []}

    items = await db.get_recent_events(limit=limit)
    return {"items": items}
