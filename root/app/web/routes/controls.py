import multiprocessing
import threading
from queue import Empty

from fastapi import APIRouter, Request
from pydantic import BaseModel

lazy from calibre_integration import (
    calibre_info,
    factory as calibre_factory,
)
from models import active_urls as active_urls_utils
from models.fanfic_info import FanficInfo
lazy from parsers import auto_url_parsers, regex_parsing
from web.routes.websocket import invalidate_history_cache

router = APIRouter(prefix="/api/controls", tags=["controls"])
_queue_surgery_lock = threading.Lock()


class _LockFactory:
    """CalibreInfo-compatible lock provider without spawning a manager process."""

    @staticmethod
    def Lock():
        return multiprocessing.Lock()


class AddUrlRequest(BaseModel):
    """Request body for adding a URL to the processing queue."""

    url: str
    force: bool = False


class AddUrlsRequest(BaseModel):
    """Request body for adding multiple URLs."""

    urls: list[str]


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


def _dequeue_matching_fics(queue_obj, target_url: str) -> list[FanficInfo]:
    """Remove matching FanficInfo entries from a multiprocessing queue."""
    if queue_obj is None:
        return []

    kept_items = []
    removed_items: list[FanficInfo] = []
    with _queue_surgery_lock:
        while True:
            try:
                item = queue_obj.get_nowait()
            except Empty:
                break
            except Exception:
                break

            if isinstance(item, FanficInfo) and item.url == target_url:
                removed_items.append(item)
            else:
                kept_items.append(item)

        for item in kept_items:
            queue_obj.put(item)

    return removed_items


def _dequeue_from_all_queues(
    state, candidate_urls: list[str]
) -> tuple[list[FanficInfo], list[FanficInfo], list[FanficInfo]]:
    """Remove matching FanficInfo entries across waiting, ingress, and worker queues."""
    waiting_removed: list[FanficInfo] = []
    ingress_removed: list[FanficInfo] = []
    worker_removed: list[FanficInfo] = []
    for candidate in candidate_urls:
        waiting_removed.extend(_dequeue_matching_fics(state.waiting_queue, candidate))
        ingress_removed.extend(_dequeue_matching_fics(state.ingress_queue, candidate))
    for queue_obj in (state.worker_queues or {}).values():
        for candidate in candidate_urls:
            worker_removed.extend(_dequeue_matching_fics(queue_obj, candidate))
    return waiting_removed, ingress_removed, worker_removed


async def _load_latest_metadata(state, url: str) -> dict:
    """Best-effort metadata lookup from history for URL actions."""
    if state.history_db is None:
        return {}
    try:
        row = await state.history_db.get_latest_download(url)
        return row or {}
    except Exception:
        return {}


def _build_fanfic(
    raw_url: str, site: str | None = None, title: str | None = None
) -> FanficInfo:
    """Create a FanficInfo using parser normalization when possible."""
    url_parsers = auto_url_parsers.generate_url_parsers_from_fanficfare()
    try:
        fanfic = regex_parsing.generate_FanficInfo_from_url(raw_url, url_parsers)
    except Exception:
        if not site:
            raise ValueError(
                "Failed to parse URL and no site parameter provided."
            ) from None
        fanfic = FanficInfo(url=raw_url, site=site)
    if site:
        fanfic.site = site
    if title:
        fanfic.title = title
    return fanfic


async def _resolve_candidate_urls(
    state, body: QueueActionRequest
) -> tuple[str, str, list[str], FanficInfo | None, str | None, str | None, str | None]:
    """Normalize `body.url`, load history metadata, and resolve canonical + candidate URLs."""
    raw_url = regex_parsing.normalize_url(body.url)
    metadata = await _load_latest_metadata(state, raw_url)
    site = body.site or metadata.get("site")
    title = body.title or metadata.get("title")
    calibre_id = body.calibre_id or metadata.get("calibre_id")

    canonical_fanfic: FanficInfo | None = None
    try:
        canonical_fanfic = _build_fanfic(raw_url, site=site, title=title)
        canonical_url = canonical_fanfic.url
    except Exception:
        canonical_url = raw_url

    candidate_urls = [canonical_url]
    if raw_url != canonical_url:
        candidate_urls.append(raw_url)

    return (
        raw_url,
        canonical_url,
        candidate_urls,
        canonical_fanfic,
        site,
        title,
        calibre_id,
    )


def _remove_from_active_urls(state, url: str) -> tuple[dict, bool]:
    """Remove URL from active map when safe."""
    if state.active_urls is None:
        return {}, True

    existing = {}
    try:
        existing = dict(state.active_urls.get(url, {}))
    except Exception:
        existing = {}

    status = existing.get("status")
    can_remove = status != "processing"
    if can_remove:
        active_urls_utils.remove_active_url(state.active_urls, url)
    return existing, can_remove


def _remove_from_active_url_candidates(
    state, candidate_urls: list[str]
) -> tuple[dict, bool]:
    """Remove any candidate URL keys from active map when not processing."""
    if state.active_urls is None:
        return {}, True

    merged_meta: dict = {}
    for candidate in candidate_urls:
        try:
            meta = dict(state.active_urls.get(candidate, {}))
        except Exception:
            meta = {}
        if meta:
            merged_meta.update(meta)
        if meta.get("status") == "processing":
            return merged_meta, False

    for candidate in candidate_urls:
        _remove_from_active_urls(state, candidate)
    return merged_meta, True


def _enqueue_fanfic(state, fanfic: FanficInfo) -> None:
    """Queue a FanficInfo and reflect it in active_urls/history."""
    active_urls_utils.mark_url_queued(
        state.active_urls,
        fanfic.url,
        site=fanfic.site,
        title=fanfic.title,
        calibre_id=fanfic.calibre_id,
    )
    state.ingress_queue.put(fanfic)
    if state.history_recorder:
        state.history_recorder.record_download_created(
            fanfic.url, fanfic.site, fanfic.behavior
        )


def _remove_from_calibre_if_possible(state, fanfic: FanficInfo) -> tuple[bool, str]:
    """Attempt calibre removal for scratch redownload."""
    if not fanfic.calibre_id:
        return True, "No Calibre entry found; queued fresh download."
    if (
        state.config is None
        or getattr(state.config, "calibre", None) is None
        or state.config_store is None
    ):
        return (
            False,
            "Calibre ID found but Calibre configuration unavailable for removal.",
        )

    try:
        cdb_info = calibre_info.CalibreInfo(state.config.calibre, _LockFactory())
        client = calibre_factory.create_calibre_client(cdb_info, state.config_store)
        client.remove_story(fanfic)
        return True, "Removed from Calibre and queued fresh download."
    except Exception as exc:
        return False, f"Failed to remove from Calibre: {exc}"


def _ingest_single_url(
    state,
    raw_url: str,
    url_parsers: dict,
    *,
    force: bool = False,
    duplicate_prefix: str = "URL already in queue",
    added_suffix: str = " to processing queue",
) -> AddUrlResponse:
    """Normalize, parse, deduplicate, mark queued, and enqueue a single URL."""
    fanfic = regex_parsing.generate_FanficInfo_from_url(raw_url, url_parsers)
    if force:
        fanfic.behavior = "force"

    if active_urls_utils.is_url_active(state.active_urls, fanfic.url):
        return AddUrlResponse(
            accepted=False,
            message=f"{duplicate_prefix}: {fanfic.url}",
        )

    active_urls_utils.mark_url_queued(
        state.active_urls, fanfic.url, site=fanfic.site, behavior=fanfic.behavior
    )
    state.ingress_queue.put(fanfic)

    if state.history_recorder:
        state.history_recorder.record_download_created(
            fanfic.url, fanfic.site, fanfic.behavior
        )

    return AddUrlResponse(
        accepted=True,
        message=f"Added {fanfic.url} (site: {fanfic.site}){added_suffix}",
    )


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

    # Mark as cancelled in active_urls. wait_processor checks this flag before
    # requeuing items from its heap, so items already consumed from waiting_queue
    # are still dropped when their timer fires instead of re-entering the pipeline.
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

    # Enqueue the fanfic, updating active_urls with a fresh dict (no heap_gen)
    # so wait_processor drops any stale heap entry when its timer expires.
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

    return ActionResponse(ok=False, message=f"Unknown daemon '{name}'")
