"""WebSocket endpoint for live dashboard updates.

Periodically snapshots system state (processes, queues, active downloads,
recent history events) and pushes JSON to all connected clients every 1-2 s.
"""

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

router = APIRouter()

# Active WebSocket connections
_connections: set[WebSocket] = set()

# Minimum interval between event-driven broadcast() calls (seconds).
_BROADCAST_MIN_INTERVAL: float = 0.1
_last_broadcast_time: float = 0.0

# Shared background snapshot task state
_latest_snapshot: dict | None = None
_bg_task: asyncio.Task | None = None  # type: ignore[type-arg]

# TTL cache for expensive historical DB queries (recent_downloads, recent_activity)
_HISTORY_CACHE_TTL: float = 10.0
_history_cache: dict[str, Any] = {
    "recent_downloads": [],
    "recent_activity": [],
    "expires_at": 0.0,
}


async def _build_snapshot(state: Any) -> dict:
    """Build a JSON-serialisable dashboard snapshot from WebState."""
    snapshot: dict[str, Any] = {"timestamp": time.time()}

    # ── Active downloads ────────────────────────────────────────
    url_metadata: dict[str, dict] = {}  # url -> {site, title, ...}
    if state.active_urls is not None:
        try:
            for url, meta in state.active_urls.items():
                if isinstance(meta, dict):
                    url_metadata[url] = meta
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
        if u in waiting_url_map:
            w_meta = waiting_url_map[u]
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
    queues: dict[str, int] = {}
    for name, queue in [
        ("ingress", state.ingress_queue),
        ("waiting", state.waiting_queue),
    ]:
        if queue is not None:
            try:
                queues[name] = queue.qsize()
            except (NotImplementedError, OSError):
                queues[name] = -1
    if state.worker_queues:
        worker_depths = {}
        for wid, q in state.worker_queues.items():
            try:
                worker_depths[wid] = q.qsize()
            except (NotImplementedError, OSError):
                worker_depths[wid] = -1
        queues["workers"] = worker_depths
    snapshot["queues"] = queues

    # ── Process status ──────────────────────────────────────────
    if state.process_status_callable:
        try:
            raw = state.process_status_callable()
            snapshot["processes"] = {name: str(info) for name, info in raw.items()}
        except Exception:
            snapshot["processes"] = {}
    else:
        snapshot["processes"] = {}

    # ── Recent history events (separate feeds, TTL-cached) ─────
    # get_recent_downloads and get_recent_activity return historical records that
    # rarely change more than once every few seconds. Cache them for
    # _HISTORY_CACHE_TTL seconds to avoid hammering SQLite every snapshot cycle.
    # get_waiting_urls() is NOT cached – it reflects live retry-backoff state.
    if state.history_db is not None:
        now_ts = snapshot["timestamp"]
        if now_ts >= _history_cache["expires_at"]:
            try:
                _history_cache[
                    "recent_downloads"
                ] = await state.history_db.get_recent_downloads(limit=20)
            except Exception:
                _history_cache["recent_downloads"] = []
            try:
                _history_cache[
                    "recent_activity"
                ] = await state.history_db.get_recent_activity(limit=20)
            except Exception:
                _history_cache["recent_activity"] = []
            _history_cache["expires_at"] = now_ts + _HISTORY_CACHE_TTL
        snapshot["recent_downloads"] = _history_cache["recent_downloads"]
        snapshot["recent_activity"] = _history_cache["recent_activity"]
    else:
        snapshot["recent_downloads"] = []
        snapshot["recent_activity"] = []

    return snapshot


async def _build_and_push_snapshot(state: Any) -> dict:
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


async def _snapshot_loop(state: Any) -> None:
    """Background task: build and push one snapshot per second indefinitely."""
    while True:
        try:
            await _build_and_push_snapshot(state)
        except Exception:
            pass
        await asyncio.sleep(1)


def _ensure_snapshot_task(state: Any) -> None:
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
