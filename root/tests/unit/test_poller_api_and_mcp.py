"""Unit tests for the library update poller REST API endpoints and MCP tools."""

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import threading
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from mcp.types import CallToolResult, TextContent
import pytest

from calibre_integration.models import CalibreStorySummary
from config import ConfigManager
from config.schemas.poller import LibraryPollerConfig, SitePollerConfig
from config.store import ConfigStore
from history.models import DownloadStatus
from history.poller_store import PollerStore, _classify_tier
from mcp_server.client import AutomatedFanficClient
from mcp_server.server import create_mcp_server
from mcp_server.tools.poller import get_poller_status, trigger_library_sync
from web.dependencies import WebState
from web.server import create_app


def _story(
    url: str,
    calibre_id: str,
    title: str,
    last_update_date: date | None,
) -> CalibreStorySummary:
    return CalibreStorySummary(
        calibre_id=calibre_id,
        title=title,
        url=url,
        tags=["In-Progress"],
        last_modified=datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc),
        last_update_date=last_update_date,
        update_date_exact=last_update_date is not None,
    )


def _tool_json(res: Any) -> dict[str, Any]:
    assert isinstance(res, CallToolResult)
    content = res.content[0]
    assert isinstance(content, TextContent)
    return json.loads(content.text)


def test_poller_store_classify_tier_none_maps_to_dormant() -> None:
    """Verify _classify_tier maps None last_update_date to dormant (matching poller_scheduler)."""
    cfg = SitePollerConfig()
    assert _classify_tier(None, cfg, date(2026, 11, 22)) == "dormant"


def test_get_poller_status_endpoint_returns_sites_tiers_and_queues(
    tmp_path: Path,
) -> None:
    """Verify GET /api/poller/status returns site budgets, tiers, up_next, events, and filtering."""
    store = PollerStore(tmp_path / "history.db")
    now = datetime.now(timezone.utc)

    ff_stories = [
        _story(
            "https://www.fanfiction.net/s/100/1/",
            calibre_id="1",
            title="Hot Story",
            last_update_date=now.date() - timedelta(days=3),
        ),
        _story(
            "https://www.fanfiction.net/s/200/1/",
            calibre_id="2",
            title="Warm Story",
            last_update_date=now.date() - timedelta(days=30),
        ),
        _story(
            "https://www.fanfiction.net/s/300/1/",
            calibre_id="3",
            title="Unknown Date Story",
            last_update_date=None,
        ),
    ]
    next_times = {
        "https://www.fanfiction.net/s/100/1/": now + timedelta(minutes=15),
        "https://www.fanfiction.net/s/200/1/": now + timedelta(hours=3),
        "https://www.fanfiction.net/s/300/1/": now + timedelta(days=5),
    }
    store.sync_site_stories("fanfiction", ff_stories, lambda s: next_times[s.url])
    store.record_probe_outcome(
        url="https://www.fanfiction.net/s/100/1/",
        site="fanfiction",
        outcome="unchanged",
        checked_at=now - timedelta(hours=2),
        next_check_at=next_times["https://www.fanfiction.net/s/100/1/"],
        remote_chapters=10,
        remote_updated_at=now.date() - timedelta(days=3),
        remote_status="In-Progress",
        error_message=None,
        advance_baseline=True,
    )
    # Seed 4 regular weekly downloads for Hot Story -> cadence_days == 7.0
    with store._connect() as conn:
        for weeks_ago in (3, 2, 1, 0):
            ts = (now - timedelta(days=weeks_ago * 7 + 1)).isoformat()
            conn.execute(
                """INSERT INTO download_events (url, site, status, started_at, completed_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    "https://www.fanfiction.net/s/100/1/",
                    "fanfiction",
                    DownloadStatus.SUCCESS.value,
                    ts,
                    ts,
                ),
            )

    poller_cfg = LibraryPollerConfig(
        enabled=True,
        library_sync_interval_hours=6.0,
        tick_interval_seconds=60.0,
        sites={
            "fanfiction": SitePollerConfig(
                enabled=True,
                max_checks_per_day=24,
                min_interval_minutes=30.0,
            ),
            "ao3": SitePollerConfig(
                enabled=False,
                max_checks_per_day=12,
                min_interval_minutes=45.0,
            ),
        },
    )
    config_store = ConfigStore(
        {
            "library_poller.enabled": poller_cfg.enabled,
            "library_poller.library_sync_interval_hours": poller_cfg.library_sync_interval_hours,
            "library_poller.tick_interval_seconds": poller_cfg.tick_interval_seconds,
            "library_poller.sites": {
                site: cfg.model_dump() for site, cfg in poller_cfg.sites.items()
            },
        }
    )

    active_polls: dict[str, object] = {
        "fanfiction": {
            "url": "https://www.fanfiction.net/s/100/1/",
            "title": "Hot Story",
        }
    }
    poller_last_sync: dict[str, str] = {
        "fanfiction": "2026-11-22T20:00:00+00:00",
    }

    state = WebState(
        config_store=config_store,
        poller_store=store,
        active_polls=active_polls,
        poller_last_sync=poller_last_sync,
    )
    app = create_app(state)
    client = TestClient(app)

    resp = client.get("/api/poller/status")
    assert resp.status_code == 200
    data = resp.json()

    assert data["enabled"] is True
    assert data["library_sync_interval_hours"] == 6.0
    assert data["tick_interval_seconds"] == 60.0
    assert set(data["sites"].keys()) == {"fanfiction", "ao3"}

    ff = data["sites"]["fanfiction"]
    assert ff["enabled"] is True
    assert ff["max_checks_per_day"] == 24
    assert ff["min_interval_minutes"] == 30.0
    assert ff["checks_last_24h"] == 1
    assert ff["tracked_count"] == 3
    assert ff["active_poll"] == {
        "url": "https://www.fanfiction.net/s/100/1/",
        "title": "Hot Story",
    }
    assert ff["last_sync_at"] == "2026-11-22T20:00:00+00:00"
    assert ff["tiers"] == {
        "hot": {"max_age_days": 14, "interval_days": 1.5},
        "warm": {"max_age_days": 90, "interval_days": 7.0},
        "cool": {"max_age_days": 365, "interval_days": 21.0},
        "dormant": {"max_age_days": None, "interval_days": 60.0},
    }
    assert ff["tier_counts"] == {"hot": 1, "warm": 1, "cool": 0, "dormant": 1}
    assert len(ff["up_next"]) == 3
    assert ff["up_next"][0]["url"] == "https://www.fanfiction.net/s/100/1/"
    assert ff["up_next"][0]["cadence_days"] == 7.0
    assert ff["up_next"][1]["cadence_days"] is None
    assert len(ff["recent_events"]) == 1
    assert ff["recent_events"][0]["outcome"] == "unchanged"

    # Verify site filtering
    filtered = client.get("/api/poller/status", params={"site": "fanfiction"})
    assert filtered.status_code == 200
    filtered_data = filtered.json()
    assert list(filtered_data["sites"].keys()) == ["fanfiction"]


def test_post_poller_sync_sets_event() -> None:
    """Verify POST /api/poller/sync sets sync_poller_event and returns 503 when absent."""
    sync_event = threading.Event()
    assert not sync_event.is_set()

    app = create_app(WebState(sync_poller_event=sync_event))
    client = TestClient(app)

    resp = client.post("/api/poller/sync")
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "message": "Library poller sync triggered",
    }
    assert sync_event.is_set() is True

    # Missing sync_poller_event returns 503
    app_missing = create_app(WebState(sync_poller_event=None))
    client_missing = TestClient(app_missing)
    resp_missing = client_missing.post("/api/poller/sync")
    assert resp_missing.status_code == 503


@pytest.mark.anyio
async def test_mcp_poller_tools_delegate_to_api() -> None:
    """Verify get_poller_status and trigger_library_sync MCP tools delegate to REST API."""
    client = AutomatedFanficClient("http://test")
    status_payload = {
        "enabled": True,
        "library_sync_interval_hours": 6.0,
        "tick_interval_seconds": 60.0,
        "sites": {"fanfiction": {"enabled": True, "tracked_count": 5}},
    }
    sync_payload = {"ok": True, "message": "Library poller sync triggered"}

    async def fake_request(
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if method == "GET" and path == "/api/poller/status":
            assert params is not None
            assert params.get("site") == "fanfiction"
            return status_payload
        if method == "POST" and path == "/api/poller/sync":
            return sync_payload
        raise AssertionError(f"Unexpected request: {method} {path}")

    with patch.object(
        client, "_request", new=AsyncMock(side_effect=fake_request)
    ) as mock_req:
        server = create_mcp_server(client)

        res_status = await server.call_tool("get_poller_status", {"site": "fanfiction"})
        assert _tool_json(res_status) == status_payload

        res_sync = await server.call_tool("trigger_library_sync", {})
        assert _tool_json(res_sync) == sync_payload

        # Also verify direct tool function invocation
        assert await get_poller_status(site="fanfiction") == status_payload
        assert await trigger_library_sync() == sync_payload
        assert mock_req.await_count == 4


def test_put_config_library_poller_persists_nested_sites(tmp_path: Path) -> None:
    """PUT /api/config/library_poller validates, hot-reloads, and persists nested sites dicts to TOML."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[email]\nemail = "user@example.com"\npassword = "secret"\nserver = "imap.example.com"\n\n'
        '[calibre]\npath = "http://localhost:8080"\n',
        encoding="utf-8",
    )

    ConfigManager.clear_cache()
    try:
        app_config = ConfigManager.load_config(config_file, force_reload=True)
        config_store = ConfigStore({})
        config_store.initialize_from_config(app_config)
        state = WebState(
            config=app_config,
            config_store=config_store,
            config_path=str(config_file),
        )
        app = create_app(state)
        client = TestClient(app)

        resp = client.put(
            "/api/config/library_poller",
            json={
                "values": {
                    "enabled": True,
                    "library_sync_interval_hours": 12.0,
                    "sites": {
                        "FanFiction": {
                            "enabled": True,
                            "max_checks_per_day": 16,
                            "hot_interval_days": 2.0,
                        },
                        "archiveofourown": {
                            "enabled": False,
                            "max_checks_per_day": 10,
                        },
                    },
                }
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["applied"] is True
        assert set(body["results"]["hot"]) >= {
            "enabled",
            "library_sync_interval_hours",
            "sites",
        }

        # Verify hot-reloaded ConfigStore has normalized keys
        stored_sites = config_store.get("library_poller.sites")
        assert isinstance(stored_sites, dict)
        assert set(stored_sites.keys()) == {"fanfiction", "archiveofourown"}
        assert stored_sites["fanfiction"]["max_checks_per_day"] == 16

        # Verify TOML file reloads cleanly with nested [library_poller.sites.*]
        reloaded = ConfigManager.load_config(config_file, force_reload=True)
        assert reloaded.library_poller.enabled is True
        assert reloaded.library_poller.library_sync_interval_hours == 12.0
        assert set(reloaded.library_poller.sites.keys()) == {
            "fanfiction",
            "archiveofourown",
        }
        assert reloaded.library_poller.sites["fanfiction"].max_checks_per_day == 16
        assert reloaded.library_poller.sites["fanfiction"].hot_interval_days == 2.0
        assert reloaded.library_poller.sites["archiveofourown"].enabled is False

        # Verify removing a site persists cleanly
        resp2 = client.put(
            "/api/config/library_poller",
            json={"values": {"sites": {"fanfiction": {"max_checks_per_day": 20}}}},
        )
        assert resp2.status_code == 200
        assert resp2.json()["applied"] is True
        reloaded2 = ConfigManager.load_config(config_file, force_reload=True)
        assert list(reloaded2.library_poller.sites.keys()) == ["fanfiction"]
        assert reloaded2.library_poller.sites["fanfiction"].max_checks_per_day == 20
    finally:
        ConfigManager.clear_cache()
