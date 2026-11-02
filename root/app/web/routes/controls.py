"""FastAPI routes for application control operations."""

from calibre_integration import factory as calibre_factory


from fastapi import APIRouter, Request
from pydantic import BaseModel

from models import active_urls as active_urls_utils
from models.fanfic_info import FanficInfo
lazy from parsers import url_patterns as auto_url_parsers
from web.services.dashboard_snapshot import invalidate_history_cache
from web.services.queue_controller import (
    _queue_surgery_lock,
    build_fanfic as _build_fanfic,
    dequeue_from_all_queues as _dequeue_from_all_queues,
    dequeue_matching_fics as _dequeue_matching_fics,
    enqueue_fanfic as _enqueue_fanfic,
    ingest_single_url,
    remove_from_active_url_candidates as _remove_from_active_url_candidates,
    remove_from_calibre_if_possible as _remove_calibre_base,
    resolve_candidate_urls as _resolve_candidate_urls_base,
)

__all__ = [
    "router",
    "calibre_factory",
    "_remove_from_calibre_if_possible",
    "_build_fanfic",
    "_dequeue_matching_fics",
    "_dequeue_from_all_queues",
    "_resolve_candidate_urls",
    "_remove_from_active_url_candidates",
    "_enqueue_fanfic",
    "_queue_surgery_lock",
    "invalidate_history_cache",
]

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


def _remove_from_calibre_if_possible(state, fanfic: FanficInfo):
    return _remove_calibre_base(state, fanfic, factory=calibre_factory)


async def _resolve_candidate_urls(state, body: QueueActionRequest):
    return await _resolve_candidate_urls_base(
        state,
        body.url,
        site=body.site,
        title=body.title,
        calibre_id=body.calibre_id,
        build_fanfic_fn=_build_fanfic,
    )


def _ingest_single_url(
    state,
    raw_url: str,
    url_parsers: dict,
    *,
    force: bool = False,
    behavior_override: str | None = None,
    duplicate_prefix: str = "URL already in queue",
    added_suffix: str = " to processing queue",
) -> AddUrlResponse:
    accepted, message = ingest_single_url(
        state,
        raw_url,
        url_parsers,
        force=force,
        behavior_override=behavior_override,
        duplicate_prefix=duplicate_prefix,
        added_suffix=added_suffix,
    )
    return AddUrlResponse(accepted=accepted, message=message)


@router.post("/add-url", response_model=AddUrlResponse)
async def add_url(request: Request, body: AddUrlRequest):
    """Add a fanfiction URL directly to the ingress queue."""
    state = request.app.state.web_state

    if state.ingress_queue is None:
        return AddUrlResponse(accepted=False, message="Ingress queue not available")

    url_parsers = auto_url_parsers.generate_url_parsers_from_fanficfare()
    return _ingest_single_url(
        state,
        body.url,
        url_parsers,
        force=body.force,
        behavior_override=body.update_method,
        duplicate_prefix="URL already in queue",
        added_suffix=" to processing queue",
    )


@router.post("/add-urls", response_model=AddUrlsResponse)
async def add_urls(request: Request, body: AddUrlsRequest):
    """Add multiple fanfiction URLs to the processing queue."""
    state = request.app.state.web_state

    if state.ingress_queue is None:
        return AddUrlsResponse(
            results=[
                AddUrlResponse(accepted=False, message="Ingress queue not available")
                for _ in body.urls
            ]
        )

    url_parsers = auto_url_parsers.generate_url_parsers_from_fanficfare()
    results = []

    for raw_url in body.urls:
        if not raw_url.strip():
            continue
        try:
            results.append(
                _ingest_single_url(
                    state,
                    raw_url,
                    url_parsers,
                    behavior_override=body.update_method,
                    duplicate_prefix="Already in queue",
                    added_suffix="",
                )
            )
        except Exception as e:
            results.append(AddUrlResponse(accepted=False, message=f"Error: {e}"))

    return AddUrlsResponse(results=results)


@router.post("/cancel", response_model=ActionResponse)
@router.post("/cancel-retry", response_model=ActionResponse)
async def cancel_retry(request: Request, body: QueueActionRequest):
    """Cancel a pending retry (waiting/backoff) or queued download for a URL."""
    state = request.app.state.web_state
    if state.ingress_queue is None or state.waiting_queue is None:
        return ActionResponse(ok=False, message="Queues not available")

    (
        _raw_url,
        canonical_url,
        candidate_urls,
        _canonical_fanfic,
        site,
        title,
        calibre_id,
    ) = await _resolve_candidate_urls(state, body)

    waiting_removed, ingress_removed, worker_removed = _dequeue_from_all_queues(
        state, candidate_urls
    )

    active_cancelled = 0
    if state.active_urls is not None:
        matched_any = False
        for candidate in candidate_urls:
            if candidate in state.active_urls:
                matched_any = True
                if active_urls_utils.mark_url_cancelled(state.active_urls, candidate):
                    active_cancelled += 1
        if not matched_any:
            active_urls_utils.mark_url_cancelled(state.active_urls, canonical_url)

    if state.history_recorder:
        state.history_recorder.record_download_abandoned(
            canonical_url,
            "Retry canceled from web UI by user request",
            site=site,
            title=title,
            calibre_id=calibre_id,
        )

    invalidate_history_cache()

    removed_count = (
        len(waiting_removed)
        + len(ingress_removed)
        + len(worker_removed)
        + active_cancelled
    )
    if removed_count == 0:
        return ActionResponse(
            ok=True,
            message=f"No pending retry or queue entry found for {canonical_url}",
        )
    return ActionResponse(ok=True, message=f"Canceled {canonical_url}")


@router.post("/retry-now", response_model=ActionResponse)
async def retry_now(request: Request, body: QueueActionRequest):
    """Immediately requeue a URL that is waiting or previously failed."""
    state = request.app.state.web_state
    if state.ingress_queue is None:
        return ActionResponse(ok=False, message="Ingress queue not available")

    (
        raw_url,
        _canonical_url,
        candidate_urls,
        canonical_fanfic,
        site,
        title,
        calibre_id,
    ) = await _resolve_candidate_urls(state, body)

    waiting_removed: list[FanficInfo] = []
    for candidate in candidate_urls:
        waiting_removed.extend(_dequeue_matching_fics(state.waiting_queue, candidate))
    if waiting_removed:
        fanfic = waiting_removed[0]
        fanfic.retry_decision = None
    else:
        if canonical_fanfic is not None:
            fanfic = canonical_fanfic
        else:
            try:
                fanfic = _build_fanfic(raw_url, site=site, title=title)
            except Exception as e:
                return ActionResponse(ok=False, message=f"Error: {e}")

    existing_meta, _ = _remove_from_active_url_candidates(state, candidate_urls)
    if not site and existing_meta.get("site"):
        site = existing_meta.get("site")
    if not title and existing_meta.get("title"):
        title = existing_meta.get("title")
    if not calibre_id and existing_meta.get("calibre_id"):
        calibre_id = existing_meta.get("calibre_id")

    if site:
        fanfic.site = site
    if title and not fanfic.title:
        fanfic.title = title
    if calibre_id and not fanfic.calibre_id:
        fanfic.calibre_id = calibre_id

    active_urls_utils.mark_url_queued(
        state.active_urls,
        fanfic.url,
        site=fanfic.site,
        title=fanfic.title,
        calibre_id=fanfic.calibre_id,
    )
    state.ingress_queue.put(fanfic)
    if state.history_recorder:
        state.history_recorder.record_download_requeued(
            fanfic.url, site=fanfic.site, title=fanfic.title
        )
    return ActionResponse(ok=True, message=f"Requeued {fanfic.url} for immediate retry")


@router.post("/redownload-scratch", response_model=ActionResponse)
async def redownload_scratch(request: Request, body: QueueActionRequest):
    """Delete from Calibre (if possible) and requeue as a fresh forced download."""
    state = request.app.state.web_state
    if state.ingress_queue is None:
        return ActionResponse(ok=False, message="Ingress queue not available")

    (
        _raw_url,
        canonical_url,
        candidate_urls,
        _canonical_fanfic,
        site,
        title,
        calibre_id,
    ) = await _resolve_candidate_urls(state, body)

    existing_meta, can_remove = _remove_from_active_url_candidates(
        state, candidate_urls
    )
    if not can_remove:
        return ActionResponse(
            ok=False,
            message="Cannot redownload while actively processing; wait for completion.",
        )

    _dequeue_from_all_queues(state, candidate_urls)

    try:
        fanfic = _build_fanfic(canonical_url, site=site, title=title)
    except Exception as e:
        return ActionResponse(ok=False, message=f"Error: {e}")

    fanfic.behavior = "force"
    fanfic.calibre_id = calibre_id or existing_meta.get("calibre_id")
    if title and not fanfic.title:
        fanfic.title = title

    removed_ok, removal_message = _remove_from_calibre_if_possible(state, fanfic)
    fanfic.calibre_id = None

    _enqueue_fanfic(state, fanfic)
    if removed_ok:
        return ActionResponse(ok=True, message=f"{removal_message} URL: {fanfic.url}")
    return ActionResponse(
        ok=True,
        message=f"Queued redownload for {fanfic.url}, but Calibre removal failed: {removal_message}",
    )


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
    site = body.site.strip()
    if not site:
        return ActionResponse(ok=False, message="Invalid site")
    state = request.app.state.web_state
    if state.config_store is None:
        if state.config is None:
            return ActionResponse(ok=False, message="Config unavailable")
        disabled_sites = list(state.config.email.disabled_sites)
        site_lower = site.lower()
        if any(s.lower() == site_lower for s in disabled_sites):
            disabled_sites = [s for s in disabled_sites if s.lower() != site_lower]
            state.config.email.disabled_sites = disabled_sites
            return ActionResponse(ok=True, message=f"Site {site} enabled")
        else:
            disabled_sites.append(site)
            state.config.email.disabled_sites = disabled_sites
            return ActionResponse(ok=True, message=f"Site {site} disabled")

    cfg = state.config_store.get_config()
    disabled_sites = list(cfg.email.disabled_sites)
    site_lower = site.lower()
    if any(s.lower() == site_lower for s in disabled_sites):
        disabled_sites = [s for s in disabled_sites if s.lower() != site_lower]
        state.config_store.set("email", "disabled_sites", disabled_sites)
        return ActionResponse(ok=True, message=f"Site {site} enabled")
    else:
        disabled_sites.append(site)
        state.config_store.set("email", "disabled_sites", disabled_sites)
        return ActionResponse(ok=True, message=f"Site {site} disabled")


@router.post("/retry-all", response_model=ActionResponse)
async def retry_all(request: Request) -> ActionResponse:
    """Requeue all downloads currently in waiting/backoff state."""
    state = request.app.state.web_state
    if state.ingress_queue is None:
        return ActionResponse(ok=False, message="Ingress queue not available")

    waiting_urls: list[str] = []
    if state.active_urls is not None:
        try:
            for url, meta in state.active_urls.items():
                if isinstance(meta, dict) and meta.get("status") == "waiting":
                    waiting_urls.append(url)
        except Exception:
            pass

    count = 0
    for url in waiting_urls:
        raw_meta = state.active_urls.get(url, {}) if state.active_urls else {}
        meta = dict(raw_meta) if isinstance(raw_meta, dict) else {}
        site_val = meta.get("site")
        site = str(site_val) if site_val else "unknown"
        title_val = meta.get("title")
        title = str(title_val) if title_val else None
        calibre_val = meta.get("calibre_id")
        calibre_id = str(calibre_val) if calibre_val else None
        try:
            fanfic = _build_fanfic(url, site=site, title=title)
        except Exception:
            continue
        fanfic.retry_decision = None
        repeats_val = meta.get("retry_count", 0)
        fanfic.repeats = (
            int(repeats_val) if isinstance(repeats_val, (int, float)) else 0
        )
        if calibre_id:
            fanfic.calibre_id = calibre_id
        if state.active_urls is not None:
            active_urls_utils.mark_url_queued(
                state.active_urls,
                url,
                site=site,
                title=title,
                calibre_id=calibre_id,
            )
        state.ingress_queue.put(fanfic)
        count += 1

    invalidate_history_cache()
    return ActionResponse(ok=True, message=f"Requeued {count} waiting downloads")


@router.post("/cancel-all", response_model=ActionResponse)
async def cancel_all(request: Request) -> ActionResponse:
    """Cancel all in-flight downloads and drain queues."""
    state = request.app.state.web_state
    with _queue_surgery_lock:
        if state.ingress_queue is not None:
            while True:
                try:
                    state.ingress_queue.get_nowait()
                except Exception:
                    break
        if state.waiting_queue is not None:
            while True:
                try:
                    state.waiting_queue.get_nowait()
                except Exception:
                    break
        if state.worker_queues is not None:
            for q in state.worker_queues.values():
                while True:
                    try:
                        q.get_nowait()
                    except Exception:
                        break

    cancelled_count = 0
    if state.active_urls is not None:
        try:
            for url in list(state.active_urls.keys()):
                if active_urls_utils.mark_url_cancelled(state.active_urls, url):
                    cancelled_count += 1
        except Exception:
            pass

    invalidate_history_cache()
    return ActionResponse(
        ok=True, message=f"Cancelled {cancelled_count} in-flight downloads"
    )


@router.post("/clear-errors", response_model=ActionResponse)
async def clear_errors(request: Request, body: ClearErrorsRequest) -> ActionResponse:
    """Clear error dismissal status for a URL or all URLs."""
    state = request.app.state.web_state
    if body.url:
        state.dismissed_error_urls.add(body.url)
    else:
        if state.active_urls is not None:
            try:
                for url in list(state.active_urls.keys()):
                    state.dismissed_error_urls.add(url)
            except Exception:
                pass
        if state.history_db is not None:
            try:
                waiting = await state.history_db.get_waiting_urls()
                for w in waiting:
                    if w.get("url"):
                        state.dismissed_error_urls.add(str(w["url"]))
                recent = await state.history_db.get_recent_downloads(limit=50)
                for r in recent:
                    if r.get("url") and (
                        r.get("error_message")
                        or r.get("status") in {"failed", "abandoned"}
                    ):
                        state.dismissed_error_urls.add(str(r["url"]))
            except Exception:
                pass

    if state.active_urls is not None:
        try:
            if body.url:
                if body.url in state.active_urls:
                    meta = dict(state.active_urls[body.url])
                    meta["error_dismissed"] = True
                    state.active_urls[body.url] = meta
            else:
                for url in list(state.active_urls.keys()):
                    meta = dict(state.active_urls[url])
                    meta["error_dismissed"] = True
                    state.active_urls[url] = meta
        except Exception:
            pass
    return ActionResponse(ok=True, message="Errors cleared")


@router.post("/restart-daemon", response_model=ActionResponse)
async def restart_daemon(
    request: Request, body: RestartDaemonRequest
) -> ActionResponse:
    """Request restart of a daemon process or service."""
    state = request.app.state.web_state
    name = body.name.strip()
    name_lower = name.lower()

    if name_lower in ("webserver", "web_server"):
        if state.web_restart_event is not None:
            state.web_restart_event.set()
            return ActionResponse(ok=True, message="Web server restart triggered")
        return ActionResponse(ok=False, message="Web restart event unavailable")

    if name_lower in (
        "supervisor",
        "coordinator",
        "emailwatcher",
        "waiter",
        "ffwaiter",
        "urlingester",
    ):
        sup_event = getattr(state, "supervisor_restart_event", None)
        if sup_event is not None:
            sup_event.set()
            return ActionResponse(
                ok=True, message=f"Supervisor restart triggered for {name}"
            )
        return ActionResponse(ok=False, message="Supervisor restart event unavailable")

    if name_lower in ("workerpool", "worker_pool", "workers"):
        worker_event = getattr(state, "worker_restart_event", None)
        if worker_event is not None:
            worker_event.set()
            return ActionResponse(ok=True, message="Worker pool restart triggered")
        sup_event = getattr(state, "supervisor_restart_event", None)
        if sup_event is not None:
            return ActionResponse(ok=True, message="Worker pool restart requested")
        return ActionResponse(ok=False, message="Worker restart event unavailable")

    return ActionResponse(ok=False, message=f"Unknown daemon '{name}'")
