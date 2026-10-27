"""Debug REST API routes for queues, coordinator locks, and filtered logs."""

import multiprocessing
import re

from fastapi import APIRouter, Query, Request

lazy from calibre_integration import (
    calibre_info,
    factory as calibre_factory,
)
from models.fanfic_info import FanficInfo
from utils import ff_logging

router = APIRouter(prefix="/api/debug", tags=["debug"])


class _LockFactory:
    """CalibreInfo-compatible lock provider without spawning a manager process."""

    @staticmethod
    def Lock():
        return multiprocessing.Lock()


def _get_calibre_client(request: Request) -> object | None:
    """Obtain or instantiate CalibreClient if available."""
    client = getattr(request.app.state, "calibre_client", None)
    if client is not None:
        return client
    state = request.app.state.web_state
    if (
        state.config is None
        or getattr(state.config, "calibre", None) is None
        or not getattr(state.config.calibre, "location", None)
    ):
        return None
    try:
        cdb_info = calibre_info.CalibreInfo(state.config.calibre, _LockFactory())
        return calibre_factory.create_calibre_client(cdb_info, state.config_store)
    except Exception:
        return None


def _resolve_calibre_book_id(client: object, query: str) -> str | int | None:
    """Resolve a query (ID, URL, or title) to a Calibre book ID."""
    q = query.strip()
    if not q:
        return None
    if q.isdigit():
        return int(q)
    if "://" in q or q.startswith(("http://", "https://")):
        if hasattr(client, "search_by_url"):
            try:
                res = client.search_by_url(q)
                if res:
                    return res
            except Exception:
                pass
        if hasattr(client, "get_story_id"):
            try:
                fanfic = FanficInfo(url=q, site="unknown")
                res = client.get_story_id(fanfic)
                if res:
                    return res
            except Exception:
                pass
        return None

    # Title substring search
    if hasattr(client, "search_by_title"):
        try:
            res = client.search_by_title(q)
            if res:
                return res
        except Exception:
            pass
    if hasattr(client, "search"):
        try:
            res = client.search(f'title:"{q}"')
            if res:
                return res[0] if isinstance(res, (list, tuple)) else res
        except Exception:
            pass
    if hasattr(client, "_execute_command_with_output"):
        try:
            out = client._execute_command_with_output(["search", f'title:"{q}"'])
            ids = [x.strip() for x in str(out).split(",") if x.strip()]
            if ids:
                return ids[0]
        except Exception:
            pass
    return None


def _get_calibre_metadata(
    client: object, book_id: str | int, url: str
) -> dict[str, object] | None:
    """Fetch metadata for a given Calibre book ID."""
    if hasattr(client, "get_story_metadata"):
        try:
            lookup_id = int(book_id) if str(book_id).isdigit() else book_id
            meta = client.get_story_metadata(lookup_id)
            if meta:
                return dict(meta)
            return None
        except Exception:
            try:
                meta = client.get_story_metadata(str(book_id))
                if meta:
                    return dict(meta)
            except Exception:
                pass
            return None

    if hasattr(client, "get_metadata"):
        try:
            fanfic = FanficInfo(url=url, site="unknown", calibre_id=str(book_id))
            meta = client.get_metadata(fanfic)
            if meta:
                return dict(meta)
        except Exception:
            pass
    return None


def _matches_filter(pattern: str, text: str) -> bool:
    """Match text against pattern using regex, falling back to case-insensitive substring."""
    if not pattern:
        return True
    try:
        regex = re.compile(pattern, re.IGNORECASE)
        return bool(regex.search(text))
    except re.error:
        return pattern.lower() in text.lower()


@router.get("/queues/inspect")
async def inspect_queues(request: Request) -> dict[str, list[dict[str, object]]]:
    """Inspect and partition active URLs into queued, processing, and waiting lists."""
    state = request.app.state.web_state
    queued: list[dict[str, object]] = []
    processing: list[dict[str, object]] = []
    waiting: list[dict[str, object]] = []

    if state.active_urls is not None:
        try:
            for url, meta in list(state.active_urls.items()):
                if not isinstance(meta, dict):
                    continue
                item = {"url": url, **meta}
                status = meta.get("status")
                if status == "queued":
                    queued.append(item)
                elif status == "processing":
                    processing.append(item)
                elif status == "waiting":
                    waiting.append(item)
        except Exception:
            pass

    return {
        "queued": queued,
        "processing": processing,
        "waiting": waiting,
    }


@router.get("/coordinator")
async def get_coordinator(request: Request) -> dict[str, object]:
    """Return published coordinator status including domain assignments and backlogs."""
    state = request.app.state.web_state
    if state.coordinator_status is None:
        return {
            "assignments": {},
            "idle_workers": [],
            "dormant_workers": [],
            "backlog": {},
        }

    try:
        status = dict(state.coordinator_status)
    except Exception:
        status = {}

    status.setdefault("assignments", {})
    status.setdefault("idle_workers", [])
    status.setdefault("dormant_workers", [])
    status.setdefault("backlog", {})
    return status


@router.get("/logs")
async def get_logs(
    request: Request,
    level: str = Query(default="ALL"),
    component: str = Query(default=""),
    search: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, object]:
    """Query recent logs with level, component, and message search filtering."""
    req_level = level.strip().upper()
    raw_logs = ff_logging.get_recent_logs(limit=2000)

    filtered: list[dict[str, object]] = []
    for entry in raw_logs:
        entry_level = str(entry.get("level", "")).lower()
        if req_level and req_level != "ALL":
            if req_level in ("ERROR", "FAILURE"):
                if entry_level not in ("error", "failure"):
                    continue
            elif req_level == "DEBUG":
                if entry_level != "debug":
                    continue
            elif req_level == "INFO":
                if entry_level != "info":
                    continue
            elif req_level in ("WARNING", "WARN"):
                if entry_level not in ("warning", "warn"):
                    continue
            elif entry_level != req_level.lower():
                continue

        msg = str(entry.get("message", ""))
        if component:
            site = str(entry.get("thread_site") or "")
            if not (
                _matches_filter(component, msg) or _matches_filter(component, site)
            ):
                continue

        if search:
            if not _matches_filter(search, msg):
                continue

        filtered.append(entry)
        if len(filtered) >= limit:
            break

    return {"items": filtered, "count": len(filtered)}


@router.get("/story/diagnostics")
async def get_story_diagnostics(
    request: Request,
    url: str = Query(..., description="Fanfiction story URL"),
) -> dict[str, object]:
    """Retrieve full autopsy diagnostics for a story URL."""
    state = request.app.state.web_state
    norm_url = url.strip()

    # 1. Active state in memory
    active_state: dict[str, object] | None = None
    if state.active_urls is not None:
        raw_active = state.active_urls.get(norm_url)
        if raw_active is not None:
            if isinstance(raw_active, dict):
                active_state = dict(raw_active)
            elif isinstance(raw_active, FanficInfo):
                active_state = {
                    "url": raw_active.url,
                    "site": raw_active.site,
                    "status": getattr(raw_active, "last_status", None) or "active",
                    "calibre_id": raw_active.calibre_id,
                    "repeats": raw_active.repeats,
                    "behavior": raw_active.behavior,
                    "title": raw_active.title,
                }
            elif hasattr(raw_active, "to_dict"):
                active_state = raw_active.to_dict()
            else:
                active_state = {
                    "status": getattr(raw_active, "status", str(raw_active))
                }

    # 2. History database
    history: dict[str, object] | None = None
    latest_download: dict[str, object] | None = None
    retry_attempts: list[dict[str, object]] = []

    if state.history_db is not None:
        try:
            latest_download = await state.history_db.get_latest_download(norm_url)
        except Exception:
            latest_download = None
        try:
            retry_attempts = await state.history_db.get_retries_for_url(norm_url)
        except Exception:
            retry_attempts = []

    if latest_download is not None or retry_attempts:
        history = {
            **(latest_download or {}),
            "latest_download": latest_download,
            "retry_attempts": retry_attempts or [],
        }

    # 3. Calibre library search & metadata
    calibre: dict[str, object] = {"in_library": False}
    calibre_meta: dict[str, object] | None = None
    client = _get_calibre_client(request)
    if client is not None:
        book_id: str | int | None = None
        if hasattr(client, "search_by_url"):
            try:
                book_id = client.search_by_url(norm_url)
            except Exception:
                book_id = None
        elif hasattr(client, "get_story_id"):
            try:
                book_id = client.get_story_id(FanficInfo(url=norm_url, site="unknown"))
            except Exception:
                book_id = None

        if book_id is not None:
            calibre_meta = _get_calibre_metadata(client, book_id, norm_url)
            if calibre_meta is not None:
                calibre = {
                    "in_library": True,
                    "id": book_id,
                    "book_id": book_id,
                    **calibre_meta,
                    "metadata": calibre_meta,
                }
                chapter_count = calibre_meta.get("chapters") or calibre_meta.get(
                    "#chapters"
                )
                if chapter_count is not None:
                    calibre.setdefault("chapter_count", chapter_count)
                calibre.setdefault("formats", calibre_meta.get("formats", []))
            else:
                calibre = {
                    "in_library": True,
                    "id": book_id,
                    "book_id": book_id,
                }

    # 4. Logs matching URL or candidate title
    candidate_titles: list[str] = []
    if active_state and active_state.get("title"):
        candidate_titles.append(str(active_state["title"]))
    if latest_download and latest_download.get("title"):
        candidate_titles.append(str(latest_download["title"]))
    if calibre_meta and calibre_meta.get("title"):
        candidate_titles.append(str(calibre_meta["title"]))

    recent_logs: list[dict[str, object]] = []
    try:
        raw_logs = ff_logging.get_recent_logs(limit=2000)
        for entry in raw_logs:
            msg = str(entry.get("message", ""))
            matched = norm_url in msg
            if not matched and candidate_titles:
                for t in candidate_titles:
                    if t and t in msg:
                        matched = True
                        break
            if matched:
                recent_logs.append(entry)
    except Exception:
        recent_logs = []

    return {
        "url": norm_url,
        "active_state": active_state,
        "history": history,
        "calibre": calibre,
        "recent_logs": recent_logs,
    }


@router.get("/calibre/book")
async def get_calibre_book(
    request: Request,
    query: str = Query(..., description="Calibre ID, story URL, or title substring"),
) -> dict[str, object]:
    """Inspect full Calibre metadata for a book resolved by ID, URL, or title."""
    client = _get_calibre_client(request)
    if client is None:
        return {
            "found": False,
            "message": "Calibre is not configured or client unavailable",
        }

    q = query.strip()
    book_id = _resolve_calibre_book_id(client, q)
    if book_id is None:
        return {
            "found": False,
            "message": f"No Calibre book found matching query: {query}",
        }

    meta = _get_calibre_metadata(client, book_id, q if "://" in q else "")
    if meta is None:
        return {
            "found": False,
            "message": f"Book with ID {book_id} has no metadata in Calibre",
        }

    resolved_id = meta.get("id", book_id)
    if str(resolved_id).isdigit():
        resolved_id = int(resolved_id)

    custom_cols = {
        k: v for k, v in meta.items() if k.startswith("#") or k.startswith("*")
    }

    return {
        "found": True,
        "id": resolved_id,
        "title": meta.get("title"),
        "authors": meta.get("authors") or meta.get("author", []),
        "formats": meta.get("formats", []),
        "custom_columns": custom_cols,
        "identifiers": meta.get("identifiers", {}),
        "metadata": meta,
    }
