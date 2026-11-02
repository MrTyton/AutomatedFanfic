"""History API routes — download events, retries, email checks, notifications."""

from fastapi import APIRouter, Query, Request

from web.services import history_service

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/downloads")
async def list_downloads(
    request: Request,
    site: str | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int | None = Query(default=None, ge=0),
):
    """Paginated list of download events with optional filters."""
    return await history_service.query_downloads(
        request.app.state.web_state.history_db,
        site=site,
        status=status,
        search=search,
        limit=limit,
        offset=offset,
        page=page,
        page_size=page_size,
    )


@router.get("/retries")
async def list_retries(
    request: Request,
    site: str | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=500),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int | None = Query(default=None, ge=0),
):
    """Paginated list of all retry events."""
    return await history_service.query_retries(
        request.app.state.web_state.history_db,
        site=site,
        search=search,
        limit=limit,
        offset=offset,
        page=page,
        page_size=page_size,
    )


@router.get("/retries/{url:path}")
async def retries_for_url(request: Request, url: str):
    """All retry events for a specific URL, ordered by attempt number."""
    return await history_service.query_retries_for_url(
        request.app.state.web_state.history_db, url
    )


@router.get("/story")
async def get_story_history(request: Request, url: str):
    """Retrieve full persistent download and retry history for a specific story URL."""
    return await history_service.query_story_history(
        request.app.state.web_state.history_db, url
    )


@router.get("/emails")
async def list_email_checks(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Paginated list of email check events."""
    return await history_service.query_email_checks(
        request.app.state.web_state.history_db, limit=limit, offset=offset
    )


@router.get("/sites")
async def list_sites(request: Request):
    """Return distinct site identifiers found in history records."""
    return await history_service.query_distinct_sites(
        request.app.state.web_state.history_db
    )


@router.get("/notifications")
async def list_notifications(
    request: Request,
    site: str | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Paginated list of notification events."""
    return await history_service.query_notifications(
        request.app.state.web_state.history_db,
        site=site,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/recent")
async def recent_events(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
):
    """Most recent events across all types (for dashboard feed)."""
    return await history_service.query_recent_events(
        request.app.state.web_state.history_db, limit=limit
    )
