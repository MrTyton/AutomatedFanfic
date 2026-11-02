"""History query service delegating database operations for web routes."""

from typing import Any


async def query_downloads(
    db: Any,
    site: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Return paginated download events with optional filters."""
    if db is None:
        return {"items": [], "total": 0}

    actual_limit = limit if limit is not None else page_size
    actual_offset = offset if offset is not None else (page - 1) * page_size

    items = await db.get_downloads(
        site=site,
        status=status,
        search=search,
        limit=actual_limit,
        offset=actual_offset,
    )
    total = await db.get_download_count(site=site, status=status, search=search)
    return {"items": items, "total": total}


async def query_retries(
    db: Any,
    site: str | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Return paginated retry events with optional filters."""
    if db is None:
        return {"items": [], "total": 0}

    actual_limit = limit if limit is not None else page_size
    actual_offset = offset if offset is not None else (page - 1) * page_size

    items = await db.get_retries(
        limit=actual_limit, offset=actual_offset, site=site, search=search
    )
    total = await db.get_retry_count(site=site, search=search)
    return {"items": items, "total": total}


async def query_retries_for_url(db: Any, url: str) -> dict[str, Any]:
    """Return all retry events for a specific URL, ordered by attempt number."""
    if db is None:
        return {"items": []}
    items = await db.get_retries_for_url(url)
    return {"items": items}


async def query_story_history(db: Any, url: str) -> dict[str, Any]:
    """Retrieve full persistent download and retry history for a story URL."""
    if db is None:
        return {"found": False, "story": None}
    story = await db.get_story_history(url)
    if not story:
        return {"found": False, "story": None}
    return {"found": True, "story": story}


async def query_email_checks(
    db: Any,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return paginated email check events."""
    if db is None:
        return {"items": [], "total": 0}
    items = await db.get_email_checks(limit=limit, offset=offset)
    total = (
        await db.get_email_checks_count()
        if hasattr(db, "get_email_checks_count")
        else len(items)
    )
    return {"items": items, "total": total}


async def query_distinct_sites(db: Any) -> dict[str, Any]:
    """Return distinct site identifiers found in history records."""
    if db is None:
        return {"sites": []}
    sites = await db.get_distinct_sites()
    return {"sites": sites}


async def query_notifications(
    db: Any,
    site: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return paginated notification events."""
    if db is None:
        return {"items": [], "total": 0}
    items = await db.get_notifications(
        limit=limit, offset=offset, site=site, search=search
    )
    total = (
        await db.get_notifications_count(site=site, search=search)
        if hasattr(db, "get_notifications_count")
        else len(items)
    )
    return {"items": items, "total": total}


async def query_recent_events(db: Any, limit: int = 20) -> dict[str, Any]:
    """Return the most recent events across all types."""
    if db is None:
        return {"items": []}
    items = await db.get_recent_events(limit=limit)
    return {"items": items}


__all__ = [
    "query_downloads",
    "query_retries",
    "query_retries_for_url",
    "query_story_history",
    "query_email_checks",
    "query_distinct_sites",
    "query_notifications",
    "query_recent_events",
]
