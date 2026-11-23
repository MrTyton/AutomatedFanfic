"""FastAPI routes for the adaptive Calibre library update poller."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from config.schemas.poller import LibraryPollerConfig
from services.library_poller import load_poller_config
from web.dependencies import WebState

__all__ = ["router"]

router = APIRouter(prefix="/api/poller", tags=["poller"])


class PollerSyncResponse(BaseModel):
    """Response for triggering an immediate library poller sync."""

    ok: bool
    message: str


def _resolve_poller_config(state: WebState) -> LibraryPollerConfig:
    """Resolve current LibraryPollerConfig from hot-reloaded ConfigStore or static AppConfig."""
    if state.config_store is not None:
        has_store_poller = any(
            state.config_store.get(key) is not None
            for key in (
                "library_poller",
                "library_poller.enabled",
                "library_poller.sites",
                "library_poller.library_sync_interval_hours",
                "library_poller.tick_interval_seconds",
            )
        )
        if has_store_poller:
            return load_poller_config(state.config_store)

    if state.config is not None:
        return state.config.library_poller

    return LibraryPollerConfig()


@router.get("/status")
async def get_poller_status(
    request: Request,
    site: str = Query(default=""),
    up_next_limit: int = Query(default=10, ge=0, le=500),
    recent_limit: int = Query(default=15, ge=0, le=500),
) -> dict[str, Any]:
    """Return adaptive library poller status, per-site budgets, tiers, and upcoming checks."""
    state: WebState = request.app.state.web_state
    poller_cfg = _resolve_poller_config(state)
    now = datetime.now(timezone.utc)
    site_filter = site.strip().lower()

    sites_payload: dict[str, dict[str, Any]] = {}
    for site_name, site_cfg in poller_cfg.sites.items():
        if site_filter and site_name != site_filter:
            continue

        if state.poller_store is not None:
            store_status = state.poller_store.get_site_status(
                site_name,
                site_cfg,
                now,
                up_next_limit=up_next_limit,
                recent_limit=recent_limit,
            )
        else:
            store_status = {
                "checks_last_24h": 0,
                "tracked_count": 0,
                "tier_counts": {"hot": 0, "warm": 0, "cool": 0, "dormant": 0},
                "up_next": [],
                "recent_events": [],
            }

        active_poll: object = None
        if state.active_polls is not None:
            try:
                active_poll = state.active_polls.get(site_name)
            except Exception:
                active_poll = None

        last_sync_at: str | None = None
        if state.poller_last_sync is not None:
            try:
                raw_sync = state.poller_last_sync.get(site_name)
                last_sync_at = raw_sync if isinstance(raw_sync, str) else None
            except Exception:
                last_sync_at = None

        sites_payload[site_name] = {
            "enabled": site_cfg.enabled,
            "max_checks_per_day": site_cfg.max_checks_per_day,
            "min_interval_minutes": site_cfg.min_interval_minutes,
            "checks_last_24h": store_status["checks_last_24h"],
            "tracked_count": store_status["tracked_count"],
            "active_poll": active_poll,
            "last_sync_at": last_sync_at,
            "tier_counts": store_status["tier_counts"],
            "up_next": store_status["up_next"],
            "recent_events": store_status["recent_events"],
        }

    return {
        "enabled": poller_cfg.enabled,
        "library_sync_interval_hours": poller_cfg.library_sync_interval_hours,
        "tick_interval_seconds": poller_cfg.tick_interval_seconds,
        "sites": sites_payload,
    }


@router.post("/sync", response_model=PollerSyncResponse)
async def trigger_poller_sync(request: Request) -> PollerSyncResponse:
    """Wake the library poller to perform an immediate Calibre library sync scan."""
    state: WebState = request.app.state.web_state
    if state.sync_poller_event is None:
        raise HTTPException(
            status_code=503,
            detail="Library poller sync event is not available",
        )
    state.sync_poller_event.set()
    return PollerSyncResponse(ok=True, message="Library poller sync triggered")
