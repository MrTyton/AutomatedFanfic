from typing import Any
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch

from utils import ff_logging
from web.dependencies import WebState
from web.server import create_app


@pytest.mark.anyio
async def test_debug_queues_inspect():
    active_urls: Any = {
        "https://ao3.org/1": {"status": "queued", "site": "ao3"},
        "https://ao3.org/2": {
            "status": "processing",
            "site": "ao3",
            "worker_id": "worker_0",
        },
        "https://ffnet.net/1": {
            "status": "waiting",
            "site": "ffnet",
            "wait_until": 1729837400,
            "retry_count": 2,
        },
        "https://ao3.org/ignore": "not-a-dict",  # malformed entry
        "https://ao3.org/cancelled": {"status": "cancelled", "site": "ao3"},
    }
    state = WebState(active_urls=active_urls)
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/queues/inspect")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["queued"]) == 1
        assert len(data["processing"]) == 1
        assert len(data["waiting"]) == 1
        assert data["waiting"][0]["retry_count"] == 2
        assert data["queued"][0]["url"] == "https://ao3.org/1"
        assert data["processing"][0]["url"] == "https://ao3.org/2"
        assert data["waiting"][0]["url"] == "https://ffnet.net/1"


@pytest.mark.anyio
async def test_debug_queues_inspect_none():
    state = WebState(active_urls=None)
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/queues/inspect")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"queued": [], "processing": [], "waiting": []}


@pytest.mark.anyio
async def test_debug_coordinator_endpoint():
    state = WebState(
        coordinator_status={
            "assignments": {"archiveofourown.org": "worker_0"},
            "idle_workers": ["worker_1"],
            "dormant_workers": [],
            "backlog": {
                "archiveofourown.org": [{"url": "https://ao3.org/1", "repeat_count": 0}]
            },
        }
    )
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/coordinator")
        assert resp.status_code == 200
        data = resp.json()
        assert data["assignments"]["archiveofourown.org"] == "worker_0"
        assert len(data["backlog"]["archiveofourown.org"]) == 1


@pytest.mark.anyio
async def test_debug_coordinator_fallback_defaults():
    state = WebState(coordinator_status=None)
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/coordinator")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {
            "assignments": {},
            "idle_workers": [],
            "dormant_workers": [],
            "backlog": {},
        }


@pytest.mark.anyio
async def test_debug_coordinator_partial_status():
    state = WebState(coordinator_status={"assignments": {"ao3": "w0"}})
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/coordinator")
        assert resp.status_code == 200
        data = resp.json()
        assert data["assignments"] == {"ao3": "w0"}
        assert data["idle_workers"] == []
        assert data["dormant_workers"] == []
        assert data["backlog"] == {}


@pytest.mark.anyio
async def test_debug_logs_filtering():
    state = WebState()
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/logs?level=ERROR&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "count" in data


@pytest.mark.anyio
async def test_debug_logs_filtering_details():
    mock_logs = [
        {
            "timestamp": "2026-10-27 12:00:00",
            "level": "debug",
            "message": "Coordinator: checking queues",
            "thread_site": None,
        },
        {
            "timestamp": "2026-10-27 12:01:00",
            "level": "info",
            "message": "(ao3) Processing story 123",
            "thread_site": "ao3",
        },
        {
            "timestamp": "2026-10-27 12:02:00",
            "level": "error",
            "message": "(ao3) Failed to download story 123: Timeout",
            "thread_site": "ao3",
        },
        {
            "timestamp": "2026-10-27 12:03:00",
            "level": "failure",
            "message": "(ffnet) Cloudflare challenge detected",
            "thread_site": "ffnet",
        },
        {
            "timestamp": "2026-10-27 12:04:00",
            "level": "info",
            "message": "Calibre: book added successfully",
            "thread_site": None,
        },
        {
            "timestamp": "2026-10-27 12:05:00",
            "level": "warning",
            "message": "FanFicFare: rate limit warning",
            "thread_site": "ffnet",
        },
    ]
    with patch.object(ff_logging, "get_recent_logs", return_value=mock_logs):
        state = WebState()
        app = create_app(state)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Level ERROR / FAILURE
            resp = await client.get("/api/debug/logs?level=ERROR")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 2
            assert all(item["level"] in ("error", "failure") for item in data["items"])

            # Level FAILURE (same as ERROR)
            resp = await client.get("/api/debug/logs?level=FAILURE")
            assert resp.status_code == 200
            assert resp.json()["count"] == 2

            # Level DEBUG
            resp = await client.get("/api/debug/logs?level=DEBUG")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 1
            assert data["items"][0]["message"] == "Coordinator: checking queues"

            # Level INFO
            resp = await client.get("/api/debug/logs?level=INFO")
            assert resp.status_code == 200
            assert resp.json()["count"] == 2

            # Level WARNING / WARN
            resp = await client.get("/api/debug/logs?level=WARN")
            assert resp.status_code == 200
            assert resp.json()["count"] == 1

            # Component filter (substring / thread_site)
            resp = await client.get("/api/debug/logs?component=ao3")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 2

            # Component regex
            resp = await client.get("/api/debug/logs?component=^Calibre")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 1
            assert "Calibre" in data["items"][0]["message"]

            # Search keyword
            resp = await client.get("/api/debug/logs?search=Cloudflare")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 1
            assert "Cloudflare" in data["items"][0]["message"]

            # Search regex
            resp = await client.get(
                "/api/debug/logs", params={"search": r"story\s+\d+"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 2

            # Limit
            resp = await client.get("/api/debug/logs?level=ALL&limit=2")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 2
            assert len(data["items"]) == 2

            # Invalid regex fallback to substring search for search
            resp = await client.get("/api/debug/logs?search=[invalid(")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 0  # didn't crash with 500

            # Invalid regex fallback to substring search for component
            resp = await client.get("/api/debug/logs?component=(ao3")
            assert resp.status_code == 200
            data = resp.json()
            # `(ao3` is invalid regex due to unclosed paren, but substring matches `(ao3) Processing story 123`
            assert data["count"] == 2

            # Limit validation (out of bounds)
            resp = await client.get("/api/debug/logs?limit=0")
            assert resp.status_code == 422
            resp = await client.get("/api/debug/logs?limit=1001")
            assert resp.status_code == 422
