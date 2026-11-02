"""Queue operations, task enqueueing, cancellation, and surgery for web routes."""

import threading
from queue import Empty
from typing import Any

from calibre_integration import calibre_info
from calibre_integration import factory as calibre_factory
from models import active_urls as active_urls_utils
from models.fanfic_info import FanficInfo
lazy from parsers import regex_parsing, url_patterns as auto_url_parsers
from web.services.calibre_lookup import _LockFactory

_queue_surgery_lock = threading.Lock()


def dequeue_matching_fics(queue_obj: Any, target_url: str) -> list[FanficInfo]:
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


def dequeue_from_all_queues(
    state: Any, candidate_urls: list[str]
) -> tuple[list[FanficInfo], list[FanficInfo], list[FanficInfo]]:
    """Remove matching FanficInfo entries across waiting, ingress, and worker queues."""
    waiting_removed: list[FanficInfo] = []
    ingress_removed: list[FanficInfo] = []
    worker_removed: list[FanficInfo] = []
    for candidate in candidate_urls:
        waiting_removed.extend(dequeue_matching_fics(state.waiting_queue, candidate))
        ingress_removed.extend(dequeue_matching_fics(state.ingress_queue, candidate))
    for queue_obj in (state.worker_queues or {}).values():
        for candidate in candidate_urls:
            worker_removed.extend(dequeue_matching_fics(queue_obj, candidate))
    return waiting_removed, ingress_removed, worker_removed


async def load_latest_metadata(state: Any, url: str) -> dict:
    """Best-effort metadata lookup from history for URL actions."""
    if state.history_db is None:
        return {}
    try:
        row = await state.history_db.get_latest_download(url)
        return row or {}
    except Exception:
        return {}


def build_fanfic(
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


async def resolve_candidate_urls(
    state: Any,
    url: str,
    site: str | None = None,
    title: str | None = None,
    calibre_id: str | None = None,
    build_fanfic_fn: Any = None,
) -> tuple[str, str, list[str], FanficInfo | None, str | None, str | None, str | None]:
    """Normalize url, load history metadata, and resolve canonical + candidate URLs."""
    raw_url = regex_parsing.normalize_url(url)
    metadata = await load_latest_metadata(state, raw_url)
    resolved_site = site or metadata.get("site")
    resolved_title = title or metadata.get("title")
    resolved_calibre_id = calibre_id or metadata.get("calibre_id")

    if build_fanfic_fn is None:
        build_fanfic_fn = build_fanfic
    canonical_fanfic: FanficInfo | None = None
    try:
        canonical_fanfic = build_fanfic_fn(
            raw_url, site=resolved_site, title=resolved_title
        )
        canonical_url = (
            canonical_fanfic.url if canonical_fanfic is not None else raw_url
        )
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
        resolved_site,
        resolved_title,
        resolved_calibre_id,
    )


def remove_from_active_urls(state: Any, url: str) -> tuple[dict, bool]:
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


def remove_from_active_url_candidates(
    state: Any, candidate_urls: list[str]
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
        remove_from_active_urls(state, candidate)
    return merged_meta, True


def enqueue_fanfic(state: Any, fanfic: FanficInfo) -> None:
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


def remove_from_calibre_if_possible(
    state: Any, fanfic: FanficInfo, factory: Any = None
) -> tuple[bool, str]:
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
        if factory is None:
            factory = calibre_factory
        client = factory.create_calibre_client(cdb_info, state.config_store)
        client.remove_story(fanfic)
        return True, "Removed from Calibre and queued fresh download."
    except Exception as exc:
        return False, f"Failed to remove from Calibre: {exc}"


def ingest_single_url(
    state: Any,
    raw_url: str,
    url_parsers: dict,
    *,
    force: bool = False,
    behavior_override: str | None = None,
    duplicate_prefix: str = "URL already in queue",
    added_suffix: str = " to processing queue",
) -> tuple[bool, str]:
    """Normalize, parse, deduplicate, mark queued, and enqueue a single URL."""
    fanfic = regex_parsing.generate_FanficInfo_from_url(raw_url, url_parsers)
    if behavior_override:
        fanfic.behavior = behavior_override
    elif force:
        fanfic.behavior = "force"

    if active_urls_utils.is_url_active(state.active_urls, fanfic.url):
        return False, f"{duplicate_prefix}: {fanfic.url}"

    active_urls_utils.mark_url_queued(
        state.active_urls, fanfic.url, site=fanfic.site, behavior=fanfic.behavior
    )
    state.ingress_queue.put(fanfic)

    if state.history_recorder:
        state.history_recorder.record_download_created(
            fanfic.url, fanfic.site, fanfic.behavior
        )

    return True, f"Added {fanfic.url} (site: {fanfic.site}){added_suffix}"
