"""WebSocket endpoint for live dashboard updates.

Periodically snapshots system state (processes, queues, active downloads,
recent history events) and pushes JSON to all connected clients every 1-2 s.
"""

import asyncio
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from web.dependencies import WebState
from web.services.dashboard_snapshot import (
    _history_cache,
    build_snapshot,
    invalidate_history_cache,
)

__all__ = [
    "router",
    "dashboard_websocket",
    "broadcast",
    "_build_snapshot",
    "_history_cache",
    "invalidate_history_cache",
]

router = APIRouter()

# Active WebSocket connections
_connections: set[WebSocket] = set()

# Minimum interval between event-driven broadcast() calls (seconds).
_BROADCAST_MIN_INTERVAL: float = 0.1
_last_broadcast_time: float = 0.0

# Shared background snapshot task state
_latest_snapshot: dict[str, object] | None = None
_bg_task: asyncio.Task[None] | None = None

# Backward compatibility alias for tests patching or calling _build_snapshot
_build_snapshot = build_snapshot


async def _build_and_push_snapshot(state: WebState) -> dict[str, object]:
    """Build one snapshot and push it to every connected client."""
    global _latest_snapshot
    snapshot = await build_snapshot(state)
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
    """Accept a WebSocket connection and stream periodic state snapshots."""
    await websocket.accept()
    _connections.add(websocket)

    state = websocket.app.state.web_state
    _ensure_snapshot_task(state)

    if _latest_snapshot is not None:
        try:
            await websocket.send_json(_latest_snapshot)
        except Exception:
            _connections.discard(websocket)
            return

    try:
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
    """Push a message to all connected WebSocket clients."""
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
