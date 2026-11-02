"""FastAPI routes for application control operations."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

lazy from parsers import url_patterns
from web.services.dashboard_snapshot import invalidate_history_cache
from web.services import queue_controller

__all__ = ["router"]

router = APIRouter(prefix="/api/controls", tags=["controls"])


class AddUrlRequest(BaseModel):
    """Request body for adding a URL to the processing queue."""

    url: str
    force: bool = False
    update_method: str | None = None


class AddUrlsRequest(BaseModel):
    """Request body for adding multiple URLs."""

    urls: list[str]
    update_method: str | None = None


class AddUrlResponse(BaseModel):
    """Response for URL addition."""

    accepted: bool
    message: str


class AddUrlsResponse(BaseModel):
    """Response for batch URL addition."""

    results: list[AddUrlResponse]


class QueueActionRequest(BaseModel):
    """Request body for queue actions on a specific URL."""

    url: str
    site: str | None = None
    title: str | None = None
    calibre_id: str | None = None


class ActionResponse(BaseModel):
    """Generic action response."""

    ok: bool
    message: str


class ToggleSiteRequest(BaseModel):
    """Request body for toggling site disabled status."""

    site: str


class ClearErrorsRequest(BaseModel):
    """Request body for clearing error dismissals."""

    url: str | None = None


class RestartDaemonRequest(BaseModel):
    """Request body for restarting a daemon service."""

    name: str


@router.post("/add-url", response_model=AddUrlResponse)
async def add_url(request: Request, body: AddUrlRequest) -> AddUrlResponse:
    """Add a fanfiction URL directly to the ingress queue."""
    state = request.app.state.web_state
    if state.ingress_queue is None:
        return AddUrlResponse(accepted=False, message="Ingress queue not available")

    url_parsers = url_patterns.generate_url_parsers_from_fanficfare()
    accepted, message = queue_controller.ingest_single_url(
        state,
        body.url,
        url_parsers,
        force=body.force,
        behavior_override=body.update_method,
        duplicate_prefix="URL already in queue",
        added_suffix=" to processing queue",
    )
    return AddUrlResponse(accepted=accepted, message=message)


@router.post("/add-urls", response_model=AddUrlsResponse)
async def add_urls(request: Request, body: AddUrlsRequest) -> AddUrlsResponse:
    """Add multiple fanfiction URLs to the processing queue."""
    state = request.app.state.web_state
    if state.ingress_queue is None:
        return AddUrlsResponse(
            results=[
                AddUrlResponse(accepted=False, message="Ingress queue not available")
                for _ in body.urls
            ]
        )

    url_parsers = url_patterns.generate_url_parsers_from_fanficfare()
    results = []
    for raw_url in body.urls:
        if not raw_url.strip():
            continue
        try:
            accepted, message = queue_controller.ingest_single_url(
                state,
                raw_url,
                url_parsers,
                behavior_override=body.update_method,
                duplicate_prefix="Already in queue",
                added_suffix="",
            )
            results.append(AddUrlResponse(accepted=accepted, message=message))
        except Exception as e:
            results.append(AddUrlResponse(accepted=False, message=f"Error: {e}"))

    return AddUrlsResponse(results=results)


@router.post("/cancel", response_model=ActionResponse)
@router.post("/cancel-retry", response_model=ActionResponse)
async def cancel_retry(request: Request, body: QueueActionRequest) -> ActionResponse:
    """Cancel a pending retry (waiting/backoff) or queued download for a URL."""
    ok, message = await queue_controller.cancel_retry_action(
        request.app.state.web_state,
        body.url,
        site=body.site,
        title=body.title,
        calibre_id=body.calibre_id,
    )
    return ActionResponse(ok=ok, message=message)


@router.post("/retry-now", response_model=ActionResponse)
async def retry_now(request: Request, body: QueueActionRequest) -> ActionResponse:
    """Immediately requeue a URL that is waiting or previously failed."""
    ok, message = await queue_controller.retry_now_action(
        request.app.state.web_state,
        body.url,
        site=body.site,
        title=body.title,
        calibre_id=body.calibre_id,
    )
    return ActionResponse(ok=ok, message=message)


@router.post("/redownload-scratch", response_model=ActionResponse)
async def redownload_scratch(
    request: Request, body: QueueActionRequest
) -> ActionResponse:
    """Delete from Calibre (if possible) and requeue as a fresh forced download."""
    ok, message = await queue_controller.redownload_scratch_action(
        request.app.state.web_state,
        body.url,
        site=body.site,
        title=body.title,
        calibre_id=body.calibre_id,
    )
    return ActionResponse(ok=ok, message=message)


@router.post("/check-emails", response_model=ActionResponse)
async def check_emails_now(request: Request) -> ActionResponse:
    """Trigger an immediate check of monitored email accounts."""
    state = request.app.state.web_state
    if state.check_emails_event is None:
        return ActionResponse(ok=False, message="Email check event not configured")
    state.check_emails_event.set()
    invalidate_history_cache()
    return ActionResponse(ok=True, message="Email check triggered")


@router.post("/toggle-coordinator", response_model=ActionResponse)
async def toggle_coordinator(request: Request) -> ActionResponse:
    """Toggle coordinator task assignment pause state."""
    state = request.app.state.web_state
    if state.coordinator_status is None:
        return ActionResponse(ok=False, message="Coordinator status unavailable")
    is_paused = bool(state.coordinator_status.get("paused", False))
    new_state = not is_paused
    state.coordinator_status["paused"] = new_state
    return ActionResponse(
        ok=True,
        message="Coordinator paused" if new_state else "Coordinator resumed",
    )


@router.post("/toggle-site", response_model=ActionResponse)
async def toggle_site(request: Request, body: ToggleSiteRequest) -> ActionResponse:
    """Toggle a site in email.disabled_sites."""
    ok, message = queue_controller.toggle_site_action(
        request.app.state.web_state, body.site
    )
    return ActionResponse(ok=ok, message=message)


@router.post("/retry-all", response_model=ActionResponse)
async def retry_all(request: Request) -> ActionResponse:
    """Requeue all downloads currently in waiting/backoff state."""
    ok, message = queue_controller.retry_all_action(request.app.state.web_state)
    return ActionResponse(ok=ok, message=message)


@router.post("/cancel-all", response_model=ActionResponse)
async def cancel_all(request: Request) -> ActionResponse:
    """Cancel all in-flight downloads and drain queues."""
    ok, message = queue_controller.cancel_all_action(request.app.state.web_state)
    return ActionResponse(ok=ok, message=message)


@router.post("/clear-errors", response_model=ActionResponse)
async def clear_errors(request: Request, body: ClearErrorsRequest) -> ActionResponse:
    """Clear error dismissal status for a URL or all URLs."""
    ok, message = await queue_controller.clear_errors_action(
        request.app.state.web_state, body.url
    )
    return ActionResponse(ok=ok, message=message)


@router.post("/restart-daemon", response_model=ActionResponse)
async def restart_daemon(
    request: Request, body: RestartDaemonRequest
) -> ActionResponse:
    """Request restart of a daemon process or service."""
    ok, message = queue_controller.restart_daemon_action(
        request.app.state.web_state, body.name
    )
    return ActionResponse(ok=ok, message=message)
