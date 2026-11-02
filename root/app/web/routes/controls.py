"""FastAPI routes for application control operations."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

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
    accepted, message = queue_controller.add_single_url_action(
        request.app.state.web_state,
        body.url,
        force=body.force,
        update_method=body.update_method,
    )
    return AddUrlResponse(accepted=accepted, message=message)


@router.post("/add-urls", response_model=AddUrlsResponse)
async def add_urls(request: Request, body: AddUrlsRequest) -> AddUrlsResponse:
    """Add multiple fanfiction URLs to the processing queue."""
    raw_results = queue_controller.ingest_multiple_urls(
        request.app.state.web_state, body.urls, update_method=body.update_method
    )
    return AddUrlsResponse(
        results=[AddUrlResponse(accepted=acc, message=msg) for acc, msg in raw_results]
    )


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
    ok, message = queue_controller.trigger_email_check_action(
        request.app.state.web_state
    )
    return ActionResponse(ok=ok, message=message)


@router.post("/toggle-coordinator", response_model=ActionResponse)
async def toggle_coordinator(request: Request) -> ActionResponse:
    """Toggle coordinator task assignment pause state."""
    ok, message = queue_controller.toggle_coordinator_action(
        request.app.state.web_state
    )
    return ActionResponse(ok=ok, message=message)


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
