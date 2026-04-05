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


async def _build_snapshot(state: Any) -> dict:
    """Build a JSON-serialisable dashboard snapshot from WebState."""
    snapshot: dict[str, Any] = {"timestamp": time.time()}

    # ── Active downloads ────────────────────────────────────────
    if state.active_urls is not None:
        try:
            urls = list(state.active_urls.keys())
        except Exception:
            urls = []
    else:
        urls = []

    # Split active URLs into truly-processing vs waiting-for-retry
    waiting_url_map: dict[str, str] = {}  # url -> started_at
    if state.history_db is not None:
        try:
            for row in await state.history_db.get_waiting_urls():
                waiting_url_map[row["url"]] = row.get("started_at", "")
        except Exception:
            pass

    processing_urls = [u for u in urls if u not in waiting_url_map]
    waiting_urls = [
        {"url": u, "started_at": waiting_url_map.get(u, "")}
        for u in urls
        if u in waiting_url_map
    ]

    snapshot["active_downloads"] = {
        "items": processing_urls,
        "count": len(processing_urls),
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

    # ── Recent history events (separate feeds) ─────────────────
    if state.history_db is not None:
        try:
            snapshot["recent_downloads"] = await state.history_db.get_recent_downloads(
                limit=20
            )
        except Exception:
            snapshot["recent_downloads"] = []
        try:
            snapshot["recent_activity"] = await state.history_db.get_recent_activity(
                limit=20
            )
        except Exception:
            snapshot["recent_activity"] = []
    else:
        snapshot["recent_downloads"] = []
        snapshot["recent_activity"] = []

    return snapshot


@router.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    """Accept a WebSocket connection and push periodic state snapshots."""
    await websocket.accept()
    _connections.add(websocket)

    state = websocket.app.state.web_state

    try:
        while True:
            snapshot = await _build_snapshot(state)
            await websocket.send_json(snapshot)
            await asyncio.sleep(1)
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

    Useful for event-driven pushes (e.g. download completed) on top of the
    periodic polling.
    """
    dead: set[WebSocket] = set()
    data = json.dumps(message)
    for ws in _connections:
        try:
            await ws.send_text(data)
        except Exception:
            dead.add(ws)
    _connections.difference_update(dead)
