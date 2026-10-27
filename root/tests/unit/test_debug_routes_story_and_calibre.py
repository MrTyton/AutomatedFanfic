"""Unit tests for story diagnostics autopsy and Calibre book inspection debug routes."""

from typing import cast
from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient
import pytest

from models.active_urls import ActiveUrlsDict
from models.fanfic_info import FanficInfo
from utils import ff_logging
from web.dependencies import WebState
from web.server import create_app


@pytest.mark.anyio
async def test_story_diagnostics_comprehensive_autopsy():
    mock_db = AsyncMock()
    mock_db.get_latest_download.return_value = {
        "id": 1,
        "status": "waiting",
        "url": "https://ao3.org/1",
    }
    mock_db.get_retries_for_url.return_value = [
        {"attempt": 1, "error_message": "525 SSL", "delay_seconds": 60}
    ]

    mock_calibre = MagicMock()
    mock_calibre.search_by_url.return_value = "101"
    mock_calibre.get_story_metadata.return_value = {
        "id": 101,
        "title": "Test Fic",
        "chapters": 10,
    }

    state = WebState(
        history_db=mock_db,
        active_urls={
            "https://ao3.org/1": {
                "status": "waiting",
                "wait_until": 1729837400,
                "retry_count": 1,
            }
        },
    )
    app = create_app(state)
    app.state.calibre_client = mock_calibre

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/story/diagnostics?url=https://ao3.org/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "https://ao3.org/1"
        assert data["active_state"]["status"] == "waiting"
        assert len(data["history"]["retry_attempts"]) == 1
        assert data["calibre"]["in_library"] is True
        assert data["calibre"]["id"] == "101" or data["calibre"]["id"] == 101


@pytest.mark.anyio
async def test_story_diagnostics_unknown_url_returns_clean_payload():
    mock_db = AsyncMock()
    mock_db.get_latest_download.return_value = None
    mock_db.get_retries_for_url.return_value = []

    mock_calibre = MagicMock()
    mock_calibre.search_by_url.return_value = None

    state = WebState(
        history_db=mock_db,
        active_urls={},
    )
    app = create_app(state)
    app.state.calibre_client = mock_calibre

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/debug/story/diagnostics?url=https://ao3.org/unknown"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data == {
            "url": "https://ao3.org/unknown",
            "active_state": None,
            "history": None,
            "calibre": {"in_library": False},
            "recent_logs": [],
        }


@pytest.mark.anyio
async def test_story_diagnostics_with_matching_logs(monkeypatch):
    test_logs = [
        {"level": "info", "message": "Starting download https://ao3.org/fic42"},
        {"level": "warning", "message": "Rate limited on https://ao3.org/fic42"},
        {"level": "info", "message": "Unrelated log about https://other.org/story"},
    ]
    monkeypatch.setattr(ff_logging, "get_recent_logs", lambda limit=2000: test_logs)

    state = WebState(active_urls={})
    app = create_app(state)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/debug/story/diagnostics?url=https://ao3.org/fic42"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["recent_logs"]) == 2
        assert "Rate limited" in data["recent_logs"][1]["message"]


@pytest.mark.anyio
async def test_calibre_book_by_id_success():
    mock_calibre = MagicMock()
    mock_calibre.get_story_metadata.return_value = {
        "id": 42,
        "title": "A Great Fanfic",
        "authors": ["Author One"],
        "formats": ["EPUB"],
        "#chapters": 15,
        "identifiers": {"url": "https://ao3.org/works/42"},
    }

    state = WebState()
    app = create_app(state)
    app.state.calibre_client = mock_calibre

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/calibre/book?query=42")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True
        assert data["id"] == 42
        assert data["title"] == "A Great Fanfic"
        assert data["authors"] == ["Author One"]
        assert data["formats"] == ["EPUB"]
        assert "#chapters" in data["custom_columns"]
        assert data["identifiers"]["url"] == "https://ao3.org/works/42"


@pytest.mark.anyio
async def test_calibre_book_by_url_success():
    mock_calibre = MagicMock()
    mock_calibre.search_by_url.return_value = "77"
    mock_calibre.get_story_metadata.return_value = {
        "id": 77,
        "title": "Found by URL",
        "authors": ["Author Two"],
        "formats": ["EPUB", "MOBI"],
        "identifiers": {"url": "https://ao3.org/works/77"},
    }

    state = WebState()
    app = create_app(state)
    app.state.calibre_client = mock_calibre

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/debug/calibre/book?query=https://ao3.org/works/77"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True
        assert data["id"] == 77
        assert data["title"] == "Found by URL"


@pytest.mark.anyio
async def test_calibre_book_by_title_substring_success():
    mock_calibre = MagicMock()
    mock_calibre.search_by_title.return_value = "88"
    mock_calibre.get_story_metadata.return_value = {
        "id": 88,
        "title": "The Fantastic Adventure",
        "authors": ["Author Three"],
        "formats": ["EPUB"],
    }

    state = WebState()
    app = create_app(state)
    app.state.calibre_client = mock_calibre

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/calibre/book?query=Fantastic")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True
        assert data["id"] == 88
        assert data["title"] == "The Fantastic Adventure"


@pytest.mark.anyio
async def test_calibre_book_not_found():
    mock_calibre = MagicMock()
    mock_calibre.search_by_url.return_value = None
    mock_calibre.get_story_metadata.return_value = None

    state = WebState()
    app = create_app(state)
    app.state.calibre_client = mock_calibre

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/calibre/book?query=99999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is False
        assert "message" in data


@pytest.mark.anyio
async def test_calibre_book_not_configured():
    state = WebState()
    app = create_app(state)
    # No app.state.calibre_client set and no state.config

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/calibre/book?query=42")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is False
        assert "message" in data


@pytest.mark.anyio
async def test_story_diagnostics_calibre_client_standard_interface():
    # Client implementing standard CalibreClient get_story_id and get_metadata
    mock_calibre = MagicMock(spec=["get_story_id", "get_metadata"])
    mock_calibre.get_story_id.return_value = "505"
    mock_calibre.get_metadata.return_value = {
        "id": 505,
        "title": "Standard Calibre Fic",
        "#chapters": 12,
        "formats": ["EPUB"],
    }

    state = WebState(active_urls={})
    app = create_app(state)
    app.state.calibre_client = mock_calibre

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/story/diagnostics?url=https://ao3.org/505")
        assert resp.status_code == 200
        data = resp.json()
        assert data["calibre"]["in_library"] is True
        assert str(data["calibre"]["id"]) == "505"
        assert data["calibre"]["chapter_count"] == 12


@pytest.mark.anyio
async def test_story_diagnostics_active_url_fanfic_info_instance():
    fanfic = FanficInfo(url="https://ao3.org/obj", site="ao3", title="Active Fic")
    setattr(fanfic, "last_status", "processing")

    state = WebState(
        active_urls=cast(ActiveUrlsDict, {"https://ao3.org/obj": fanfic}),
    )
    app = create_app(state)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/story/diagnostics?url=https://ao3.org/obj")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_state"] is not None
        assert data["active_state"]["url"] == "https://ao3.org/obj"


@pytest.mark.anyio
async def test_story_diagnostics_logs_match_by_title(monkeypatch):
    test_logs = [
        {"level": "info", "message": "Updating 'UniqueTitleStory' in calibre"},
    ]
    monkeypatch.setattr(ff_logging, "get_recent_logs", lambda limit=2000: test_logs)

    mock_db = AsyncMock()
    mock_db.get_latest_download.return_value = {
        "id": 1,
        "title": "UniqueTitleStory",
        "url": "https://ao3.org/u1",
    }
    mock_db.get_retries_for_url.return_value = []

    state = WebState(history_db=mock_db, active_urls={})
    app = create_app(state)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/story/diagnostics?url=https://ao3.org/u1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["recent_logs"]) == 1
        assert "UniqueTitleStory" in data["recent_logs"][0]["message"]
