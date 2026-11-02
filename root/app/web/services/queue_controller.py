"""Queue operations, task enqueueing, cancellation, and surgery for web routes."""

import threading
from queue import Empty
from typing import Any

from calibre_integration import calibre_info
from calibre_integration import factory as calibre_factory
from models.active_urls import (
    is_url_active,
    mark_url_cancelled,
    mark_url_queued,
    remove_active_url,
)
from models.fanfic_info import FanficInfo
lazy from parsers import regex_parsing, url_patterns
from web.services.calibre_lookup import _LockFactory
from web.services.dashboard_snapshot import invalidate_history_cache

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
    url_parsers = url_patterns.generate_url_parsers_from_fanficfare()
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
) -> tuple[str, str, list[str], FanficInfo | None, str | None, str | None, str | None]:
    """Normalize url, load history metadata, and resolve canonical + candidate URLs."""
    raw_url = regex_parsing.normalize_url(url)
    metadata = await load_latest_metadata(state, raw_url)
    resolved_site = site or metadata.get("site")
    resolved_title = title or metadata.get("title")
    resolved_calibre_id = calibre_id or metadata.get("calibre_id")

    canonical_fanfic: FanficInfo | None = None
    try:
        canonical_fanfic = build_fanfic(
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
        remove_active_url(state.active_urls, url)
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
    mark_url_queued(
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


def remove_from_calibre_if_possible(state: Any, fanfic: FanficInfo) -> tuple[bool, str]:
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

    if is_url_active(state.active_urls, fanfic.url):
        return False, f"{duplicate_prefix}: {fanfic.url}"

    mark_url_queued(
        state.active_urls, fanfic.url, site=fanfic.site, behavior=fanfic.behavior
    )
    state.ingress_queue.put(fanfic)

    if state.history_recorder:
        state.history_recorder.record_download_created(
            fanfic.url, fanfic.site, fanfic.behavior
        )

    return True, f"Added {fanfic.url} (site: {fanfic.site}){added_suffix}"


async def cancel_retry_action(
    state: Any,
    url: str,
    site: str | None = None,
    title: str | None = None,
    calibre_id: str | None = None,
) -> tuple[bool, str]:
    """Cancel a pending retry (waiting/backoff) or queued download for a URL."""
    if state.ingress_queue is None or state.waiting_queue is None:
        return False, "Queues not available"

    (
        _raw_url,
        canonical_url,
        candidate_urls,
        _canonical_fanfic,
        resolved_site,
        resolved_title,
        resolved_calibre_id,
    ) = await resolve_candidate_urls(
        state, url, site=site, title=title, calibre_id=calibre_id
    )

    waiting_removed, ingress_removed, worker_removed = dequeue_from_all_queues(
        state, candidate_urls
    )

    active_cancelled = 0
    if state.active_urls is not None:
        matched_any = False
        for candidate in candidate_urls:
            if candidate in state.active_urls:
                matched_any = True
                if mark_url_cancelled(state.active_urls, candidate):
                    active_cancelled += 1
        if not matched_any:
            mark_url_cancelled(state.active_urls, canonical_url)

    if state.history_recorder:
        state.history_recorder.record_download_abandoned(
            canonical_url,
            "Retry canceled from web UI by user request",
            site=resolved_site,
            title=resolved_title,
            calibre_id=resolved_calibre_id,
        )

    invalidate_history_cache()

    removed_count = (
        len(waiting_removed)
        + len(ingress_removed)
        + len(worker_removed)
        + active_cancelled
    )
    if removed_count == 0:
        return True, f"No pending retry or queue entry found for {canonical_url}"
    return True, f"Canceled {canonical_url}"


async def retry_now_action(
    state: Any,
    url: str,
    site: str | None = None,
    title: str | None = None,
    calibre_id: str | None = None,
) -> tuple[bool, str]:
    """Immediately requeue a URL that is waiting or previously failed."""
    if state.ingress_queue is None:
        return False, "Ingress queue not available"

    (
        raw_url,
        _canonical_url,
        candidate_urls,
        canonical_fanfic,
        resolved_site,
        resolved_title,
        resolved_calibre_id,
    ) = await resolve_candidate_urls(
        state, url, site=site, title=title, calibre_id=calibre_id
    )

    waiting_removed: list[FanficInfo] = []
    for candidate in candidate_urls:
        waiting_removed.extend(dequeue_matching_fics(state.waiting_queue, candidate))
    if waiting_removed:
        fanfic = waiting_removed[0]
        fanfic.retry_decision = None
    else:
        if canonical_fanfic is not None:
            fanfic = canonical_fanfic
        else:
            try:
                fanfic = build_fanfic(raw_url, site=resolved_site, title=resolved_title)
            except Exception as e:
                return False, f"Error: {e}"

    existing_meta, _ = remove_from_active_url_candidates(state, candidate_urls)
    if not resolved_site and existing_meta.get("site"):
        resolved_site = existing_meta.get("site")
    if not resolved_title and existing_meta.get("title"):
        resolved_title = existing_meta.get("title")
    if not resolved_calibre_id and existing_meta.get("calibre_id"):
        resolved_calibre_id = existing_meta.get("calibre_id")

    if resolved_site:
        fanfic.site = resolved_site
    if resolved_title and not fanfic.title:
        fanfic.title = resolved_title
    if resolved_calibre_id and not fanfic.calibre_id:
        fanfic.calibre_id = resolved_calibre_id

    mark_url_queued(
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
    return True, f"Requeued {fanfic.url} for immediate retry"


async def redownload_scratch_action(
    state: Any,
    url: str,
    site: str | None = None,
    title: str | None = None,
    calibre_id: str | None = None,
) -> tuple[bool, str]:
    """Delete from Calibre (if possible) and requeue as a fresh forced download."""
    if state.ingress_queue is None:
        return False, "Ingress queue not available"

    (
        _raw_url,
        canonical_url,
        candidate_urls,
        _canonical_fanfic,
        resolved_site,
        resolved_title,
        resolved_calibre_id,
    ) = await resolve_candidate_urls(
        state, url, site=site, title=title, calibre_id=calibre_id
    )

    existing_meta, can_remove = remove_from_active_url_candidates(state, candidate_urls)
    if not can_remove:
        return (
            False,
            "Cannot redownload while actively processing; wait for completion.",
        )

    dequeue_from_all_queues(state, candidate_urls)

    try:
        fanfic = build_fanfic(canonical_url, site=resolved_site, title=resolved_title)
    except Exception as e:
        return False, f"Error: {e}"

    fanfic.behavior = "force"
    fanfic.calibre_id = resolved_calibre_id or existing_meta.get("calibre_id")
    if resolved_title and not fanfic.title:
        fanfic.title = resolved_title

    removed_ok, removal_message = remove_from_calibre_if_possible(state, fanfic)
    fanfic.calibre_id = None

    enqueue_fanfic(state, fanfic)
    if removed_ok:
        return True, f"{removal_message} URL: {fanfic.url}"
    return (
        True,
        f"Queued redownload for {fanfic.url}, but Calibre removal failed: {removal_message}",
    )


def toggle_site_action(state: Any, site: str) -> tuple[bool, str]:
    """Toggle a site in email.disabled_sites."""
    site = site.strip()
    if not site:
        return False, "Invalid site"

    if state.config_store is None:
        if state.config is None:
            return False, "Config unavailable"
        disabled_sites = list(state.config.email.disabled_sites)
        site_lower = site.lower()
        if any(s.lower() == site_lower for s in disabled_sites):
            disabled_sites = [s for s in disabled_sites if s.lower() != site_lower]
            state.config.email.disabled_sites = disabled_sites
            return True, f"Site {site} enabled"
        disabled_sites.append(site)
        state.config.email.disabled_sites = disabled_sites
        return True, f"Site {site} disabled"

    raw_disabled = state.config_store.get("email.disabled_sites", [])
    if not isinstance(raw_disabled, list) and state.config is not None:
        raw_disabled = list(state.config.email.disabled_sites)
    disabled_sites = [str(s) for s in (raw_disabled or [])]
    site_lower = site.lower()
    if any(s.lower() == site_lower for s in disabled_sites):
        disabled_sites = [s for s in disabled_sites if s.lower() != site_lower]
        state.config_store.update("email.disabled_sites", disabled_sites)
        if (
            state.config is not None
            and getattr(state.config, "email", None) is not None
        ):
            state.config.email.disabled_sites = disabled_sites
        return True, f"Site {site} enabled"

    disabled_sites.append(site)
    state.config_store.update("email.disabled_sites", disabled_sites)
    if state.config is not None and getattr(state.config, "email", None) is not None:
        state.config.email.disabled_sites = disabled_sites
    return True, f"Site {site} disabled"


def retry_all_action(state: Any) -> tuple[bool, str]:
    """Requeue all downloads currently in waiting/backoff state."""
    if state.ingress_queue is None:
        return False, "Ingress queue not available"

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
            fanfic = build_fanfic(url, site=site, title=title)
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
            mark_url_queued(
                state.active_urls,
                url,
                site=site,
                title=title,
                calibre_id=calibre_id,
            )
        state.ingress_queue.put(fanfic)
        count += 1

    invalidate_history_cache()
    return True, f"Requeued {count} waiting downloads"


def cancel_all_action(state: Any) -> tuple[bool, str]:
    """Cancel all in-flight downloads and drain queues."""
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
                if mark_url_cancelled(state.active_urls, url):
                    cancelled_count += 1
        except Exception:
            pass

    invalidate_history_cache()
    return True, f"Cancelled {cancelled_count} in-flight downloads"


async def clear_errors_action(state: Any, url: str | None) -> tuple[bool, str]:
    """Clear error dismissal status for a URL or all URLs."""
    if url:
        state.dismissed_error_urls.add(url)
    else:
        if state.active_urls is not None:
            try:
                for u in list(state.active_urls.keys()):
                    state.dismissed_error_urls.add(u)
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
            if url:
                if url in state.active_urls:
                    meta = dict(state.active_urls[url])
                    meta["error_dismissed"] = True
                    state.active_urls[url] = meta
            else:
                for u in list(state.active_urls.keys()):
                    meta = dict(state.active_urls[u])
                    meta["error_dismissed"] = True
                    state.active_urls[u] = meta
        except Exception:
            pass
    return True, "Errors cleared"


def restart_daemon_action(state: Any, name: str) -> tuple[bool, str]:
    """Request restart of a daemon process or service."""
    name = name.strip()
    name_lower = name.lower()

    if name_lower in ("webserver", "web_server"):
        if state.web_restart_event is not None:
            state.web_restart_event.set()
            return True, "Web server restart triggered"
        return False, "Web restart event unavailable"

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
            return True, f"Supervisor restart triggered for {name}"
        return False, "Supervisor restart event unavailable"

    if name_lower in ("workerpool", "worker_pool", "workers"):
        worker_event = getattr(state, "worker_restart_event", None)
        if worker_event is not None:
            worker_event.set()
            return True, "Worker pool restart triggered"
        sup_event = getattr(state, "supervisor_restart_event", None)
        if sup_event is not None:
            return True, "Worker pool restart requested"
        return False, "Worker restart event unavailable"

    return False, f"Unknown daemon '{name}'"


def add_single_url_action(
    state: Any,
    url: str,
    force: bool = False,
    update_method: str | None = None,
) -> tuple[bool, str]:
    """Ingest a single fanfiction URL into the processing queue."""
    if state.ingress_queue is None:
        return False, "Ingress queue not available"

    parsers_map = url_patterns.generate_url_parsers_from_fanficfare()
    return ingest_single_url(
        state,
        url,
        parsers_map,
        force=force,
        behavior_override=update_method,
        duplicate_prefix="URL already in queue",
        added_suffix=" to processing queue",
    )


def ingest_multiple_urls(
    state: Any,
    urls: list[str],
    update_method: str | None = None,
) -> list[tuple[bool, str]]:
    """Ingest multiple fanfiction URLs into the processing queue."""
    if state.ingress_queue is None:
        return [(False, "Ingress queue not available") for _ in urls]

    parsers_map = url_patterns.generate_url_parsers_from_fanficfare()
    results: list[tuple[bool, str]] = []
    for raw_url in urls:
        if not raw_url.strip():
            continue
        try:
            accepted, message = ingest_single_url(
                state,
                raw_url,
                parsers_map,
                behavior_override=update_method,
                duplicate_prefix="Already in queue",
                added_suffix="",
            )
            results.append((accepted, message))
        except Exception as e:
            results.append((False, f"Error: {e}"))
    return results


def trigger_email_check_action(state: Any) -> tuple[bool, str]:
    """Trigger an immediate check of monitored email accounts."""
    if state.check_emails_event is None:
        return False, "Email check event not configured"
    state.check_emails_event.set()
    invalidate_history_cache()
    return True, "Email check triggered"


def toggle_coordinator_action(state: Any) -> tuple[bool, str]:
    """Toggle coordinator task assignment pause state."""
    if state.coordinator_status is None:
        return False, "Coordinator status unavailable"
    is_paused = bool(state.coordinator_status.get("paused", False))
    new_state = not is_paused
    state.coordinator_status["paused"] = new_state
    return True, "Coordinator paused" if new_state else "Coordinator resumed"
