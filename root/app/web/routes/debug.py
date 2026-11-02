"""Debug REST API routes for queues, coordinator locks, and filtered logs."""

import asyncio
import re

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from models.fanfic_info import FanficInfo
import ff_logging
lazy from antibot import flaresolverr as flaresolverr_utils
from web.services.calibre_lookup import (
    get_calibre_client,
    get_calibre_metadata,
    resolve_calibre_book_id,
)
from web.services.diagnostics_service import (
    check_antibot_status,
    check_flaresolverr_reachable,
    inspect_cookiejar_file,
    resolve_config_for_url,
    run_dry_run_extraction,
    run_service_diagnostics,
    simulate_email_parse,
)

router = APIRouter(prefix="/api/debug", tags=["debug"])

# Backwards compatibility aliases
_get_calibre_client = get_calibre_client
_resolve_calibre_book_id = resolve_calibre_book_id
_get_calibre_metadata = get_calibre_metadata
_check_flaresolverr_reachable = check_flaresolverr_reachable


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

    history: dict[str, object] | None = None
    latest_download: dict[str, object] | None = None
    retry_attempts: list[dict[str, object]] = []

    if state.history_db is not None:
        try:
            latest_download = await state.history_db.get_latest_download(norm_url)
        except Exception:
            latest_download = None
        try:
            dl_id = latest_download.get("id") if latest_download else None
            retry_attempts = await state.history_db.get_retries_for_url(
                norm_url, download_event_id=dl_id
            )
        except Exception:
            retry_attempts = []

    if latest_download is not None or retry_attempts:
        history = {
            **(latest_download or {}),
            "latest_download": latest_download,
            "retry_attempts": retry_attempts or [],
        }

    calibre: dict[str, object] = {"in_library": False}
    calibre_meta: dict[str, object] | None = None
    client = get_calibre_client(request.app.state)
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
            calibre_meta = get_calibre_metadata(client, book_id, norm_url)
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
    client = get_calibre_client(request.app.state)
    if client is None:
        return {
            "found": False,
            "message": "Calibre is not configured or client unavailable",
        }

    q = query.strip()
    book_id = resolve_calibre_book_id(client, q)
    if book_id is None:
        return {
            "found": False,
            "message": f"No Calibre book found matching query: {query}",
        }

    meta = get_calibre_metadata(client, book_id, q if "://" in q else "")
    if meta is None:
        return {
            "found": False,
            "message": f"Book with ID {book_id} has no metadata in Calibre",
        }

    resolved_id = meta.get("id", book_id)
    if str(resolved_id).isdigit():
        resolved_id = int(str(resolved_id))

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


class ResolveConfigRequest(BaseModel):
    """Request body for resolving configuration directives for a URL."""

    url: str


class DryRunRequest(BaseModel):
    """Request body for FanFicFare metadata-only dry-run."""

    url: str


class SimulateEmailRequest(BaseModel):
    """Request body for testing URL extraction against raw email subject and body."""

    subject: str
    body: str


class FlareSolverrRecoverRequest(BaseModel):
    """Request body for recovering FlareSolverr sessions."""

    target_site: str = ""


@router.get("/cookiejar/{domain}")
async def inspect_cookiejar(request: Request, domain: str) -> dict[str, object]:
    """Inspect cookies for domain without leaking secret tokens."""
    state = request.app.state.web_state
    return inspect_cookiejar_file(state, domain)


@router.get("/antibot")
async def get_antibot_status(request: Request) -> dict[str, object]:
    """Test FlareSolverr connectivity and local Anubis Argon2id solver readiness."""
    state = request.app.state.web_state
    return await check_antibot_status(state)


@router.post("/flaresolverr/recover")
async def recover_flaresolverr_sessions(
    request: Request, body: FlareSolverrRecoverRequest | None = None
) -> dict[str, object]:
    """Recover from FlareSolverr tab crashes by destroying dead sessions."""
    state = request.app.state.web_state
    personal_path = ""
    if getattr(state, "config", None) and getattr(state.config, "calibre", None):
        personal_path = state.config.calibre.personal_ini
    elif getattr(state, "config_store", None):
        personal_path = state.config_store.get_resolved_personal_ini()

    target_site = body.target_site.strip() if body and body.target_site else None
    recovered = flaresolverr_utils.recover_flaresolverr_crashes(
        target_site=target_site,
        personal_ini_path=personal_path,
    )
    return {
        "ok": True,
        "recovered": recovered,
        "target_site": target_site,
    }


@router.post("/resolve-config")
async def resolve_config(
    request: Request, body: ResolveConfigRequest
) -> dict[str, object]:
    """Extract FanFicFare adapter, configuration directives, and Calibre strategy for a URL."""
    state = request.app.state.web_state
    return resolve_config_for_url(state, body.url)


@router.post("/diagnostics/{service}")
async def run_diagnostics(request: Request, service: str) -> dict[str, object]:
    """Run connectivity/health diagnostics for an external service."""
    state = request.app.state.web_state
    client = get_calibre_client(request.app.state)
    res = run_service_diagnostics(state, client, service)
    if res.get("status") == "error" and str(res.get("message", "")).startswith(
        "Unknown diagnostic service"
    ):
        raise HTTPException(status_code=400, detail=str(res.get("message", "")))
    return res


@router.post("/dry-run")
async def dry_run_fanfic(request: Request, body: DryRunRequest) -> dict[str, object]:
    """Run FanFicFare metadata extraction without downloading chapters."""
    state = request.app.state.web_state
    url = body.url.strip()
    return await asyncio.to_thread(run_dry_run_extraction, state, url)


@router.post("/simulate-email")
async def simulate_email(
    request: Request, body: SimulateEmailRequest
) -> dict[str, object]:
    """Simulate URL extraction against sample email text."""
    return simulate_email_parse(body.subject, body.body)
