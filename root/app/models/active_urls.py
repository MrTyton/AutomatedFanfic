"""Centralized helpers for mutating shared `active_urls` state and inspecting queue depths.

`active_urls` is backed by a `multiprocessing.Manager().dict()`. Mutating nested
dictionaries in place does not propagate across processes; callers must always
read a copy, modify it, and re-assign `active_urls[url] = entry`. This module
encapsulates that pattern and provides a single source of truth for URL status
transitions and queue-depth snapshots.
"""

from typing import Any


def is_url_active(active_urls: Any, url: str) -> bool:
    """Return True if `url` is present in `active_urls` and not marked `'cancelled'`."""
    if active_urls is None or url not in active_urls:
        return False
    try:
        meta = active_urls.get(url, {})
        if isinstance(meta, dict) and meta.get("status") == "cancelled":
            return False
    except Exception:
        pass
    return True


def remove_active_url(active_urls: Any, url: str) -> None:
    """Safely remove `url` from `active_urls` if present."""
    if active_urls is None:
        return
    try:
        if url in active_urls:
            del active_urls[url]
    except Exception:
        pass


def mark_url_queued(
    active_urls: Any,
    url: str,
    site: str | None = None,
    *,
    title: str | None = None,
    calibre_id: str | None = None,
    behavior: str | None = None,
    merge: bool = False,
    pop_keys: tuple[str, ...] = (),
) -> None:
    """Mark `url` as `'queued'` in `active_urls`.

    When `merge=False` (default), writes a fresh dictionary (clearing any prior
    `heap_gen` token so stale waiter entries are dropped). When `merge=True`,
    merges into the existing entry while removing any keys in `pop_keys`.
    """
    if active_urls is None:
        return
    try:
        entry: dict[str, Any] = dict(active_urls.get(url, {})) if merge else {}
        for k in pop_keys:
            entry.pop(k, None)
        if site is not None:
            entry["site"] = site
        if title is not None:
            entry["title"] = title
        if calibre_id is not None:
            entry["calibre_id"] = calibre_id
        if behavior is not None:
            entry["behavior"] = behavior
        entry["status"] = "queued"
        active_urls[url] = entry
    except Exception:
        pass


def mark_url_processing(
    active_urls: Any,
    url: str,
    site: str | None = None,
) -> None:
    """Mark `url` as `'processing'` in `active_urls`, preserving existing metadata."""
    if active_urls is None:
        return
    try:
        existing = dict(active_urls.get(url, {}))
        if site is not None:
            existing.setdefault("site", site)
        existing["status"] = "processing"
        active_urls[url] = existing
    except Exception:
        pass


def update_url_title(
    active_urls: Any,
    url: str,
    title: str,
    site: str | None = None,
    status: str = "processing",
) -> None:
    """Merge extracted `title` (and `site`/`status`) into an active URL entry."""
    if active_urls is None:
        return
    try:
        existing = dict(active_urls.get(url, {}))
        if site is not None:
            existing["site"] = site
        existing["title"] = title
        existing["status"] = status
        active_urls[url] = existing
    except Exception:
        pass


def mark_url_waiting(
    active_urls: Any,
    url: str,
    site: str | None = None,
    *,
    title: str | None = None,
    calibre_id: str | None = None,
    heap_gen: int | None = None,
    delete_if_cancelled: bool = False,
) -> bool:
    """Mark `url` as `'waiting'` in `active_urls` unless it has been cancelled.

    Returns:
        bool: True if the entry was updated to `'waiting'`, False if it was
        already `'cancelled'` (or if an error occurred).
    """
    if active_urls is None:
        return True
    try:
        existing = dict(active_urls.get(url, {}))
        if existing.get("status") == "cancelled":
            if delete_if_cancelled:
                remove_active_url(active_urls, url)
            return False
        if site is not None:
            existing.setdefault("site", site)
        if title:
            existing["title"] = title
        if calibre_id:
            existing["calibre_id"] = calibre_id
        existing["status"] = "waiting"
        if heap_gen is not None:
            existing["heap_gen"] = heap_gen
        active_urls[url] = existing
        return True
    except Exception:
        return False


def mark_url_failed(
    active_urls: Any,
    url: str,
    error_message: str,
) -> None:
    """Mark `url` as `'failed'` with `error` in `active_urls` if present."""
    if active_urls is None or url not in active_urls:
        return
    try:
        entry = dict(active_urls[url])
        entry["status"] = "failed"
        entry["error"] = error_message
        active_urls[url] = entry
    except Exception:
        pass


def mark_url_cancelled(active_urls: Any, url: str) -> bool:
    """Mark `url` as `'cancelled'` in `active_urls`.

    Returns:
        bool: True if the entry existed and its status was changed to `'cancelled'`,
        False otherwise.
    """
    if active_urls is None:
        return False
    try:
        raw_existing = active_urls.get(url, {})
        existing = dict(raw_existing) if isinstance(raw_existing, dict) else {}
        was_changed = url in active_urls and existing.get("status") != "cancelled"
        existing["status"] = "cancelled"
        active_urls[url] = existing
        return was_changed
    except Exception:
        return False


def get_queue_depths(
    ingress_queue: Any,
    waiting_queue: Any,
    worker_queues: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return current queue sizes across ingress, waiting, and worker queues."""
    result: dict[str, Any] = {}
    for name, queue in [
        ("ingress", ingress_queue),
        ("waiting", waiting_queue),
    ]:
        if queue is not None:
            try:
                result[name] = queue.qsize()
            except NotImplementedError, OSError:
                result[name] = -1

    if worker_queues:
        worker_depths: dict[str, int] = {}
        for wid, q in worker_queues.items():
            try:
                worker_depths[wid] = q.qsize()
            except NotImplementedError, OSError:
                worker_depths[wid] = -1
        result["workers"] = worker_depths

    return result
