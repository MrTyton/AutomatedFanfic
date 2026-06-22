"""Control API routes — add URLs, trigger actions."""

import threading
from queue import Empty

from fastapi import APIRouter, Request
from pydantic import BaseModel

from models.fanfic_info import FanficInfo

router = APIRouter(prefix="/api/controls", tags=["controls"])
_queue_surgery_lock = threading.Lock()


class _LockFactory:
    """CalibreInfo-compatible lock provider without spawning a manager process."""

    @staticmethod
    def Lock():
        import multiprocessing

        return multiprocessing.Lock()


class AddUrlRequest(BaseModel):
    """Request body for adding a URL to the processing queue."""

    url: str


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


def _normalize_url(url: str) -> str:
    """Normalize URL for parser/site detection."""
    raw_url = url.strip()
    if raw_url and not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url
    return raw_url


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


async def _load_latest_metadata(state, url: str) -> dict:
    """Best-effort metadata lookup from history for URL actions."""
    if state.history_db is None:
        return {}
    try:
        row = await state.history_db.get_latest_download(url)
        return row or {}
    except Exception:
        return {}


def _build_fanfic(raw_url: str, site: str | None = None, title: str | None = None) -> FanficInfo:
    """Create a FanficInfo using parser normalization when possible."""
    from parsers import auto_url_parsers
    from parsers import regex_parsing

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
        try:
            if url in state.active_urls:
                del state.active_urls[url]
        except Exception:
            pass
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
    if state.active_urls is not None:
        state.active_urls[fanfic.url] = {
            "site": fanfic.site,
            "title": fanfic.title,
            "status": "queued",
            "calibre_id": fanfic.calibre_id,
        }
    state.ingress_queue.put(fanfic)
    if state.history_recorder:
        state.history_recorder.record_download_created(
            fanfic.url, fanfic.site, fanfic.behavior
        )


def _remove_from_calibre_if_possible(state, fanfic: FanficInfo) -> tuple[bool, str]:
    """Attempt calibre removal for scratch redownload."""
    if not fanfic.calibre_id:
        return True, "No Calibre entry found; queued fresh download."
    if not state.config_path:
        return False, "Calibre ID found but config path unavailable for removal."

    try:
        from calibre_integration import calibre_info, calibredb_utils
        cdb_info = calibre_info.CalibreInfo(state.config_path, _LockFactory())
        client = calibredb_utils.CalibreDBClient(cdb_info)
        client.remove_story(fanfic)
        return True, "Removed from Calibre and queued fresh download."
    except Exception as exc:
        return False, f"Failed to remove from Calibre: {exc}"


@router.post("/add-url", response_model=AddUrlResponse)
async def add_url(request: Request, body: AddUrlRequest):
    """Add a fanfiction URL directly to the ingress queue."""
    state = request.app.state.web_state

    if state.ingress_queue is None:
        return AddUrlResponse(accepted=False, message="Ingress queue not available")

    from parsers import regex_parsing
    from parsers import auto_url_parsers

    # Normalize URL: add https:// if no protocol present (parsers require it for site detection)
    raw_url = body.url.strip()
    if raw_url and not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url

    # Parse the URL to create a FanficInfo
    url_parsers = auto_url_parsers.generate_url_parsers_from_fanficfare()
    fanfic = regex_parsing.generate_FanficInfo_from_url(raw_url, url_parsers)

    # Check for duplicates (use normalized fanfic.url, not raw_url)
    if state.active_urls is not None and fanfic.url in state.active_urls:
        return AddUrlResponse(
            accepted=False, message=f"URL already in queue: {fanfic.url}"
        )

    # Add to active_urls and queue
    if state.active_urls is not None:
        state.active_urls[fanfic.url] = {"site": fanfic.site, "status": "queued"}

    state.ingress_queue.put(fanfic)

    if state.history_recorder:
        state.history_recorder.record_download_created(
            fanfic.url, fanfic.site, fanfic.behavior
        )

    return AddUrlResponse(
        accepted=True,
        message=f"Added {fanfic.url} (site: {fanfic.site}) to processing queue",
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

    from parsers import regex_parsing
    from parsers import auto_url_parsers

    url_parsers = auto_url_parsers.generate_url_parsers_from_fanficfare()
    results = []

    for raw_url in body.urls:
        raw_url = raw_url.strip()
        if not raw_url:
            continue
        # Normalize URL: add https:// if no protocol present
        if not raw_url.startswith(("http://", "https://")):
            raw_url = "https://" + raw_url
        try:
            fanfic = regex_parsing.generate_FanficInfo_from_url(raw_url, url_parsers)

            if state.active_urls is not None and fanfic.url in state.active_urls:
                results.append(
                    AddUrlResponse(
                        accepted=False,
                        message=f"Already in queue: {fanfic.url}",
                    )
                )
                continue

            if state.active_urls is not None:
                state.active_urls[fanfic.url] = {
                    "site": fanfic.site,
                    "status": "queued",
                }

            state.ingress_queue.put(fanfic)

            if state.history_recorder:
                state.history_recorder.record_download_created(
                    fanfic.url, fanfic.site, fanfic.behavior
                )

            results.append(
                AddUrlResponse(
                    accepted=True,
                    message=f"Added {fanfic.url} (site: {fanfic.site})",
                )
            )
        except Exception as e:
            results.append(AddUrlResponse(accepted=False, message=f"Error: {e}"))

    return AddUrlsResponse(results=results)


@router.post("/cancel-retry", response_model=ActionResponse)
async def cancel_retry(request: Request, body: QueueActionRequest):
    """Cancel a pending retry (waiting/backoff) for a URL."""
    state = request.app.state.web_state
    if state.ingress_queue is None or state.waiting_queue is None:
        return ActionResponse(ok=False, message="Queues not available")

    raw_url = _normalize_url(body.url)
    metadata = await _load_latest_metadata(state, raw_url)
    site = body.site or metadata.get("site")
    try:
        canonical_url = _build_fanfic(raw_url, site=site).url
    except Exception:
        canonical_url = raw_url
    candidate_urls = [canonical_url]
    if raw_url != canonical_url:
        candidate_urls.append(raw_url)

    waiting_removed: list[FanficInfo] = []
    ingress_removed: list[FanficInfo] = []
    for candidate in candidate_urls:
        waiting_removed.extend(_dequeue_matching_fics(state.waiting_queue, candidate))
        ingress_removed.extend(_dequeue_matching_fics(state.ingress_queue, candidate))
    for queue_obj in (state.worker_queues or {}).values():
        for candidate in candidate_urls:
            _dequeue_matching_fics(queue_obj, candidate)

    _remove_from_active_url_candidates(state, candidate_urls)

    if state.history_recorder:
        state.history_recorder.record_download_abandoned(
            canonical_url,
            "Retry canceled from web UI by user request",
            site=site,
        )

    removed_count = len(waiting_removed) + len(ingress_removed)
    if removed_count == 0:
        return ActionResponse(
            ok=True, message=f"No pending retry found for {canonical_url}"
        )
    return ActionResponse(ok=True, message=f"Canceled retry for {canonical_url}")


@router.post("/retry-now", response_model=ActionResponse)
async def retry_now(request: Request, body: QueueActionRequest):
    """Immediately requeue a URL that is waiting or previously failed."""
    state = request.app.state.web_state
    if state.ingress_queue is None:
        return ActionResponse(ok=False, message="Ingress queue not available")

    raw_url = _normalize_url(body.url)
    metadata = await _load_latest_metadata(state, raw_url)
    site = body.site or metadata.get("site")
    title = body.title or metadata.get("title")

    canonical_fanfic: FanficInfo | None = None
    try:
        canonical_fanfic = _build_fanfic(raw_url, site=site, title=title)
        canonical_url = canonical_fanfic.url
    except Exception:
        canonical_url = raw_url
    candidate_urls = [canonical_url]
    if raw_url != canonical_url:
        candidate_urls.append(raw_url)

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

    if site:
        fanfic.site = site
    if title and not fanfic.title:
        fanfic.title = title

    _remove_from_active_url_candidates(state, candidate_urls)
    _enqueue_fanfic(state, fanfic)
    return ActionResponse(ok=True, message=f"Requeued {fanfic.url} for immediate retry")


@router.post("/redownload-scratch", response_model=ActionResponse)
async def redownload_scratch(request: Request, body: QueueActionRequest):
    """Delete from Calibre (if possible) and requeue as a fresh forced download."""
    state = request.app.state.web_state
    if state.ingress_queue is None:
        return ActionResponse(ok=False, message="Ingress queue not available")

    raw_url = _normalize_url(body.url)
    metadata = await _load_latest_metadata(state, raw_url)
    site = body.site or metadata.get("site")
    title = body.title or metadata.get("title")
    calibre_id = body.calibre_id or metadata.get("calibre_id")

    try:
        canonical_url = _build_fanfic(raw_url, site=site, title=title).url
    except Exception:
        canonical_url = raw_url
    candidate_urls = [canonical_url]
    if raw_url != canonical_url:
        candidate_urls.append(raw_url)

    existing_meta, can_remove = _remove_from_active_url_candidates(state, candidate_urls)
    if not can_remove:
        return ActionResponse(
            ok=False,
            message="Cannot redownload while actively processing; wait for completion.",
        )

    for queue_obj in (state.ingress_queue, state.waiting_queue):
        for candidate in candidate_urls:
            _dequeue_matching_fics(queue_obj, candidate)
    for queue_obj in (state.worker_queues or {}).values():
        for candidate in candidate_urls:
            _dequeue_matching_fics(queue_obj, candidate)

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
