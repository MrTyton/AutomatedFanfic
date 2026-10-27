"""End-to-end integration tests for FastMCP server running against a live FastAPI application."""

import json
import multiprocessing
from unittest.mock import MagicMock, patch

import pytest

from mcp_server.client import AutomatedFanficClient
from mcp_server.server import create_mcp_server
from models.fanfic_info import FanficInfo
from utils import ff_logging
from web.dependencies import WebState
from web.server import create_app


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.anyio
async def test_mcp_e2e_tool_execution():
    """Verify tool execution end-to-end against a live FastAPI app instance."""
    state = WebState(
        active_urls={
            "https://archiveofourown.org/works/999": {
                "status": "queued",
                "site": "archiveofourown",
            }
        }
    )
    app = create_app(state)
    client = AutomatedFanficClient.from_app(app)
    server = create_mcp_server(client)

    queues_result = await server.call_tool("inspect_queues", {})
    assert len(queues_result.content) > 0
    assert "https://archiveofourown.org/works/999" in queues_result.content[0].text


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.anyio
async def test_mcp_e2e_full_tool_suite_integration():
    """Verify all 8 core MCP tools execute against live FastAPI endpoints."""
    sample_url = "https://archiveofourown.org/works/999"
    new_url = "https://archiveofourown.org/works/12345"
    ingress_q = multiprocessing.Queue()

    state = WebState(
        active_urls={
            sample_url: {
                "status": "queued",
                "site": "archiveofourown",
                "title": "Integration Test Fic",
            }
        },
        coordinator_status={
            "assignments": {"ao3-worker": "archiveofourown.org"},
            "idle_workers": ["ffnet-worker"],
            "dormant_workers": [],
            "backlog": {"archiveofourown.org": 1},
        },
        ingress_queue=ingress_q,
    )
    app = create_app(state)

    # 1. Provide mock calibre client for test_calibre_connection
    mock_calibre = MagicMock()
    mock_calibre.get_version.return_value = "7.16.0"
    app.state.calibre_client = mock_calibre

    client = AutomatedFanficClient.from_app(app)
    server = create_mcp_server(client)

    # Tool 1: inspect_queues
    res_queues = await server.call_tool("inspect_queues", {})
    queues_data = json.loads(res_queues.content[0].text)
    assert len(queues_data["queued"]) == 1
    assert queues_data["queued"][0]["url"] == sample_url

    # Tool 2: get_system_overview
    res_system = await server.call_tool("get_system_overview", {})
    system_data = json.loads(res_system.content[0].text)
    assert system_data["status"] == "ok"

    # Tool 3: inspect_coordinator_locks
    res_coord = await server.call_tool("inspect_coordinator_locks", {})
    coord_data = json.loads(res_coord.content[0].text)
    assert coord_data["assignments"]["ao3-worker"] == "archiveofourown.org"
    assert "ffnet-worker" in coord_data["idle_workers"]

    # Tool 4: query_logs
    marker_message = "e2e_mcp_integration_test_log_event"
    ff_logging.log(marker_message)
    res_logs = await server.call_tool("query_logs", {"search": marker_message})
    logs_data = json.loads(res_logs.content[0].text)
    assert logs_data["count"] >= 1
    assert any(marker_message in item.get("message", "") for item in logs_data["items"])

    # Tool 5: get_story_diagnostics
    res_diag = await server.call_tool(
        "get_story_diagnostics",
        {"url": sample_url},
    )
    diag_data = json.loads(res_diag.content[0].text)
    assert diag_data["url"] == sample_url
    assert diag_data["active_state"]["status"] == "queued"
    assert diag_data["active_state"]["title"] == "Integration Test Fic"

    # Tool 6: test_calibre_connection
    res_calibre = await server.call_tool("test_calibre_connection", {})
    calibre_data = json.loads(res_calibre.content[0].text)
    assert calibre_data["status"] == "ok"
    assert calibre_data["details"]["version"] == "7.16.0"

    # Tool 7: dry_run_fanfic_url
    mock_adapter = MagicMock()
    mock_adapter.getSiteDomain.return_value = "archiveofourown.org"
    mock_adapter.getMetadata.side_effect = lambda k: (
        "Dry Run Title" if k == "title" else "Dry Run Author"
    )
    mock_adapter.num_chapters.return_value = 8
    with patch("fanficfare.adapters.getAdapter", return_value=mock_adapter):
        res_dry = await server.call_tool(
            "dry_run_fanfic_url",
            {"url": sample_url},
        )
    dry_data = json.loads(res_dry.content[0].text)
    assert dry_data["status"] == "ok"
    assert dry_data["title"] == "Dry Run Title"
    assert dry_data["chapters"] == 8

    # Tool 8: inject_download
    res_inject = await server.call_tool(
        "inject_download",
        {"url": new_url, "force": True},
    )
    inject_data = json.loads(res_inject.content[0].text)
    assert inject_data["accepted"] is True
    assert "archiveofourown.org/works/12345" in inject_data["message"]

    # Verify background side-effects of inject_download
    enqueued_fic = ingress_q.get_nowait()
    assert isinstance(enqueued_fic, FanficInfo)
    assert enqueued_fic.url == "archiveofourown.org/works/12345"
    assert enqueued_fic.behavior == "force"
    assert "archiveofourown.org/works/12345" in state.active_urls
    assert state.active_urls["archiveofourown.org/works/12345"]["status"] == "queued"
