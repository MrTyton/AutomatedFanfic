"""WebSocket endpoint for live dashboard updates.

Periodically snapshots system state (processes, queues, active downloads,
recent history events) and pushes JSON to all connected clients every 1-2 s.
"""

import asyncio
import json
import os
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from models import active_urls as active_urls_utils
from web.dependencies import WebState

router = APIRouter()

# Active WebSocket connections
_connections: set[WebSocket] = set()

# Minimum interval between event-driven broadcast() calls (seconds).
_BROADCAST_MIN_INTERVAL: float = 0.1
_last_broadcast_time: float = 0.0

# Shared background snapshot task state
_latest_snapshot: dict[str, object] | None = None
_bg_task: asyncio.Task[None] | None = None

# TTL cache for expensive historical DB queries (recent_downloads, recent_activity)
_HISTORY_CACHE_TTL: float = 10.0
_history_cache: dict[str, object] = {
    "recent_downloads": [],
    "recent_activity": [],
    "expires_at": 0.0,
}


def invalidate_history_cache() -> None:
    """Reset the historical database queries cache TTL so the next broadcast fetches fresh data."""
    _history_cache["expires_at"] = 0.0


async def _build_snapshot(state: WebState) -> dict[str, object]:
    """Build a JSON-serialisable dashboard snapshot from WebState."""
    now_ts = time.time()
    snapshot: dict[str, object] = {"timestamp": now_ts}

    # ── Active downloads ────────────────────────────────────────
    url_metadata: dict[str, dict[str, object]] = {}  # url -> {site, title, ...}
    if state.active_urls is not None:
        try:
            for url, meta in state.active_urls.items():
                if isinstance(meta, dict):
                    url_metadata[url] = dict(meta)
                else:
                    url_metadata[url] = {}
        except Exception:
            pass

    urls = list(url_metadata.keys())

    # Split active URLs into truly-processing vs waiting-for-retry
    waiting_url_map: dict[str, dict] = {}  # url -> waiting row metadata
    if state.history_db is not None:
        try:
            for row in await state.history_db.get_waiting_urls():
                waiting_url_map[row["url"]] = row
        except Exception:
            pass

    # Separate into: truly processing (worker thread active), queued (accepted but not
    # yet dispatched), and waiting (retry backoff).
    # Single pass: cache per-URL dict lookups to avoid redundant .get() calls.
    active_urls_list: list[dict] = []
    queued_urls: list[dict] = []
    waiting_urls: list[dict] = []
    for u in urls:
        meta = url_metadata.get(u, {})
        if meta.get("status") == "cancelled":
            continue  # being cleaned up by wait_processor; hide from UI immediately
        if u in waiting_url_map or meta.get("status") == "waiting":
            w_meta = waiting_url_map.get(u, {})
            waiting_urls.append(
                {
                    "url": u,
                    "updated_at": w_meta.get("updated_at", ""),
                    "site": meta.get("site") or w_meta.get("site"),
                    "title": meta.get("title") or w_meta.get("title"),
                    "calibre_id": meta.get("calibre_id") or w_meta.get("calibre_id"),
                    "error_message": meta.get("error_message")
                    or w_meta.get("error_message"),
                    **meta,
                }
            )
        elif meta.get("status") == "processing":
            active_urls_list.append({"url": u, **meta})
        else:
            queued_urls.append({"url": u, **meta})

    active_urls_list.sort(
        key=lambda x: (float(x.get("queued_at") or 0.0), str(x.get("url") or ""))
    )
    queued_urls.sort(
        key=lambda x: (float(x.get("queued_at") or 0.0), str(x.get("url") or ""))
    )
    waiting_urls.sort(
        key=lambda x: (float(x.get("queued_at") or 0.0), str(x.get("url") or ""))
    )

    snapshot["active_downloads"] = {
        "items": active_urls_list,
        "count": len(active_urls_list),
    }
    snapshot["queued_downloads"] = {
        "items": queued_urls,
        "count": len(queued_urls),
    }
    snapshot["waiting_downloads"] = {
        "items": waiting_urls,
        "count": len(waiting_urls),
    }

    # ── Queue depths ────────────────────────────────────────────
    snapshot["queues"] = active_urls_utils.get_queue_depths(
        state.ingress_queue, state.waiting_queue, state.worker_queues
    )

    # ── Process status ──────────────────────────────────────────
    if state.process_status_callable:
        try:
            raw = state.process_status_callable()
            snapshot["processes"] = {name: str(info) for name, info in raw.items()}
        except Exception:
            snapshot["processes"] = {}
    else:
        snapshot["processes"] = {}

    is_coord_paused = (
        bool(state.coordinator_status.get("paused", False))
        if state.coordinator_status
        else False
    )
    snapshot["coordinator_paused"] = is_coord_paused

    disabled_sites: list[str] = []
    if state.config_store is not None:
        ds = state.config_store.get("email.disabled_sites")
        if isinstance(ds, list):
            disabled_sites = [str(s) for s in ds]
    elif state.config is not None and getattr(state.config, "email", None) is not None:
        disabled_sites = list(state.config.email.disabled_sites)
    snapshot["disabled_sites"] = disabled_sites

    max_normal_retries = 11
    if state.config is not None and getattr(state.config, "retry", None) is not None:
        max_normal_retries = getattr(state.config.retry, "max_normal_retries", 11)
    snapshot["max_normal_retries"] = max_normal_retries

    calibre_server_url: str | None = None
    if state.config is not None and getattr(state.config, "calibre", None) is not None:
        c_path = getattr(state.config.calibre, "path", "")
        if isinstance(c_path, str) and c_path.startswith("http"):
            calibre_server_url = c_path
    snapshot["calibre_server_url"] = calibre_server_url

    # Default processes for daemon_details if empty
    daemon_processes = (
        dict(snapshot["processes"])
        if snapshot["processes"]
        else {
            "WebServer": "running",
            "Coordinator": "paused" if is_coord_paused else "running",
            "EmailWatcher": "running",
            "FFWaiter": "running",
        }
    )

    daemon_roles = {
        "WebServer": "FastAPI Web Dashboard & REST/WebSocket server",
        "Coordinator": "Task scheduler with domain locking politeness policy",
        "EmailWatcher": "IMAP email poller for fanfiction update alerts",
        "UrlIngester": "IMAP email poller for fanfiction update alerts",
        "Waiter": "Exponential backoff retry queue scheduler",
        "FFWaiter": "Exponential backoff retry queue scheduler",
        "WorkerPool": "Site-specific download worker pool",
    }

    uptime_base = getattr(state, "_started_at", None)
    if not isinstance(uptime_base, (int, float)):
        uptime_base = now_ts
        setattr(state, "_started_at", uptime_base)

    daemon_details: dict[str, dict[str, object]] = {}
    for name, status in daemon_processes.items():
        st = "paused" if name == "Coordinator" and is_coord_paused else str(status)
        daemon_details[name] = {
            "name": name,
            "status": st,
            "pid": 0,
            "uptime_sec": max(1, int(now_ts - uptime_base)),
            "restarts": 0,
            "role": daemon_roles.get(name, "Background service daemon"),
        }
    snapshot["daemon_details"] = daemon_details

    # ── Site worker stats ───────────────────────────────────────
    known_adapters = [
        "archiveofourown.org",
        "fanfiction.net",
        "royalroad.com",
        "wattpad.com",
        "spacebattles.com",
        "sufficientvelocity.com",
        "questionablequesting.com",
        "fictionpress.com",
    ]
    seen_sites = set(known_adapters)
    for a in active_urls_list:
        s = a.get("site")
        if s:
            seen_sites.add(str(s).lower())
    for q in queued_urls:
        s = q.get("site")
        if s:
            seen_sites.add(str(s).lower())
    for w in waiting_urls:
        s = w.get("site")
        if s:
            seen_sites.add(str(s).lower())
    for ds_site in disabled_sites:
        if ds_site:
            seen_sites.add(ds_site.lower())

    disabled_set = {ds_site.lower() for ds_site in disabled_sites}
    catalog_sites: list[dict[str, object]] = []
    for site in sorted(seen_sites):
        active_for_site = [
            a for a in active_urls_list if str(a.get("site", "")).lower() == site
        ]
        queued_for_site = [
            q for q in queued_urls if str(q.get("site", "")).lower() == site
        ]
        waiting_for_site = [
            w for w in waiting_urls if str(w.get("site", "")).lower() == site
        ]

        if site in disabled_set:
            status_str = "disabled"
        elif active_for_site:
            status_str = "downloading"
        elif queued_for_site:
            status_str = "queued"
        elif waiting_for_site:
            status_str = "backoff"
        else:
            status_str = "idle"

        active_fic = (
            active_for_site[0]
            if active_for_site
            else (queued_for_site[0] if queued_for_site else None)
        )
        waiting_fic = waiting_for_site[0] if waiting_for_site else None

        catalog_sites.append(
            {
                "site": site,
                "status": status_str,
                "queued_count": len(queued_for_site) + len(active_for_site),
                "active_url": (active_fic.get("url") if active_fic else None)
                or (waiting_fic.get("url") if waiting_fic else None),
                "active_title": (active_fic.get("title") if active_fic else None)
                or (waiting_fic.get("title") if waiting_fic else None),
                "backoff_until": waiting_fic.get("wait_until") if waiting_fic else None,
                "attempt_number": (
                    waiting_fic.get("retry_count") if waiting_fic else None
                ),
            }
        )

    status_weights = {
        "downloading": 0,
        "queued": 1,
        "backoff": 2,
        "disabled": 3,
        "idle": 4,
    }
    catalog_sites.sort(
        key=lambda x: (
            status_weights.get(str(x.get("status", "idle")), 4),
            str(x.get("site", "")),
        )
    )
    notable_sites = [s for s in catalog_sites if s.get("status") != "idle"]

    max_threads = os.cpu_count() or 4
    snapshot["site_worker_stats"] = {
        "active_threads": len(active_urls_list),
        "max_threads": max(max_threads, 4),
        "notable_sites": notable_sites,
        "catalog_sites": catalog_sites,
    }

    # ── Recent history events (separate feeds, TTL-cached) ─────
    # get_recent_downloads and get_recent_activity return historical records that
    # rarely change more than once every few seconds. Cache them for
    # _HISTORY_CACHE_TTL seconds to avoid hammering SQLite every snapshot cycle.
    # get_waiting_urls() is NOT cached – it reflects live retry-backoff state.
    if state.history_db is not None:
        expires_at = _history_cache.get("expires_at", 0.0)
        if isinstance(expires_at, (int, float)) and now_ts >= expires_at:
            try:
                _history_cache["recent_downloads"] = (
                    await state.history_db.get_recent_downloads(limit=20)
                )
            except Exception:
                _history_cache["recent_downloads"] = []
            try:
                _history_cache["recent_activity"] = (
                    await state.history_db.get_recent_activity(limit=20)
                )
            except Exception:
                _history_cache["recent_activity"] = []
            try:
                checks = await state.history_db.get_email_checks(limit=1)
                _history_cache["last_email_check"] = checks[0] if checks else None
            except Exception:
                _history_cache["last_email_check"] = None
            _history_cache["expires_at"] = now_ts + _HISTORY_CACHE_TTL
        snapshot["recent_downloads"] = _history_cache["recent_downloads"]
        snapshot["recent_activity"] = _history_cache["recent_activity"]
        snapshot["last_email_check"] = _history_cache.get("last_email_check")
    else:
        snapshot["recent_downloads"] = []
        snapshot["recent_activity"] = []
        snapshot["last_email_check"] = None

    return snapshot


async def _build_and_push_snapshot(state: WebState) -> dict[str, object]:
    """Build one snapshot and push it to every connected client.

    Dead connections (those that raise on send) are removed from ``_connections``.
    Returns the snapshot dict (also stored in ``_latest_snapshot``).
    """
    global _latest_snapshot
    snapshot = await _build_snapshot(state)
    _latest_snapshot = snapshot
    dead: set[WebSocket] = set()
    for ws in list(_connections):
        try:
            await ws.send_json(snapshot)
        except Exception:
            dead.add(ws)
    _connections.difference_update(dead)
    return snapshot


async def _snapshot_loop(state: WebState) -> None:
    """Background task: build and push one snapshot per second while clients are connected."""
    while True:
        if _connections:
            try:
                await _build_and_push_snapshot(state)
            except Exception:
                pass
        await asyncio.sleep(1)


def _ensure_snapshot_task(state: WebState) -> None:
    """Start the shared background snapshot task if it is not already running."""
    global _bg_task
    if _bg_task is None or _bg_task.done():
        _bg_task = asyncio.get_running_loop().create_task(_snapshot_loop(state))


@router.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    """Accept a WebSocket connection and stream periodic state snapshots.

    A single shared background task (``_snapshot_loop``) builds one snapshot
    per second and pushes it to all connected clients.  This handler registers
    the client, sends the most-recent snapshot immediately (if one exists), then
    simply waits for the client to disconnect.
    """
    await websocket.accept()
    _connections.add(websocket)

    state = websocket.app.state.web_state
    _ensure_snapshot_task(state)

    # Deliver the cached snapshot immediately so the client gets data right away
    # without waiting for the next background-task cycle.
    if _latest_snapshot is not None:
        try:
            await websocket.send_json(_latest_snapshot)
        except Exception:
            _connections.discard(websocket)
            return

    try:
        # Keep the connection alive; the background task handles all sends.
        # websocket.receive() will raise WebSocketDisconnect when the client leaves.
        while True:
            await websocket.receive()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _connections.discard(websocket)
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass


async def broadcast(message: dict) -> None:
    """Push a message to all connected WebSocket clients.

    Calls arriving within _BROADCAST_MIN_INTERVAL of the previous broadcast
    are silently dropped to prevent flooding clients with high-frequency events.
    Useful for event-driven pushes (e.g. download completed) on top of the
    periodic polling.
    """
    global _last_broadcast_time
    now = time.time()
    if now - _last_broadcast_time < _BROADCAST_MIN_INTERVAL:
        return
    _last_broadcast_time = now

    dead: set[WebSocket] = set()
    data = json.dumps(message)
    for ws in _connections:
        try:
            await ws.send_text(data)
        except Exception:
            dead.add(ws)
    _connections.difference_update(dead)
