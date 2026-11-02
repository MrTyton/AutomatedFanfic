"""Debug REST API routes for queues, coordinator locks, and filtered logs."""

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from antibot.cookies import inspect_cookiejar_file
from web.services.calibre_lookup import (
    get_calibre_client,
    inspect_calibre_book,
)
from web.services.diagnostics_service import (
    build_story_diagnostics,
    check_antibot_status,
    get_coordinator_state,
    inspect_queues_state,
    query_filtered_logs,
    recover_flaresolverr_action,
    resolve_config_for_url,
    run_dry_run_extraction,
    run_service_diagnostics,
    simulate_email_parse,
)

router = APIRouter(prefix="/api/debug", tags=["debug"])


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


@router.get("/queues/inspect")
async def inspect_queues(request: Request) -> dict[str, list[dict[str, object]]]:
    """Inspect and partition active URLs into queued, processing, and waiting lists."""
    return inspect_queues_state(request.app.state.web_state)


@router.get("/coordinator")
async def get_coordinator(request: Request) -> dict[str, object]:
    """Return published coordinator status including domain assignments and backlogs."""
    return get_coordinator_state(request.app.state.web_state)


@router.get("/logs")
async def get_logs(
    level: str = Query(default="ALL"),
    component: str = Query(default=""),
    search: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, object]:
    """Query recent logs with level, component, and message search filtering."""
    return query_filtered_logs(
        level=level, component=component, search=search, limit=limit
    )


@router.get("/story/diagnostics")
async def get_story_diagnostics(
    request: Request,
    url: str = Query(..., description="Fanfiction story URL"),
) -> dict[str, object]:
    """Retrieve full autopsy diagnostics for a story URL."""
    state = request.app.state.web_state
    client = get_calibre_client(request.app.state)
    return await build_story_diagnostics(state, client, url)


@router.get("/calibre/book")
async def get_calibre_book(
    request: Request,
    query: str = Query(..., description="Calibre ID, story URL, or title substring"),
) -> dict[str, object]:
    """Inspect full Calibre metadata for a book resolved by ID, URL, or title."""
    client = get_calibre_client(request.app.state)
    return inspect_calibre_book(client, query)


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
    target_site = body.target_site if body is not None else None
    return recover_flaresolverr_action(state, target_site)


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
