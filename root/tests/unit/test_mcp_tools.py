"""Unit tests for FastMCP modular tool suite."""

import json
from typing import Any
from unittest.mock import AsyncMock
from mcp.types import CallToolResult, TextContent
import pytest

from mcp_server.base import _current_client, get_client, set_client
from mcp_server.client import AutomatedFanficClient
from mcp_server.server import create_mcp_server
from mcp_server.tools.antibot import inspect_cookiejar, test_antibot_status
from mcp_server.tools.calibre import inspect_calibre_book, test_calibre_connection
from mcp_server.tools.config import resolve_config_for_url
from mcp_server.tools.controls import cancel_download, inject_download, retry_now
from mcp_server.tools.diagnostics import (
    dry_run_fanfic_url,
    simulate_email_parse,
    test_email_connection,
    test_notification,
)
from mcp_server.tools.logs import query_logs
from mcp_server.tools.queues import inspect_queues
from mcp_server.tools.story import get_story_diagnostics
from mcp_server.tools.system import get_system_overview, inspect_coordinator_locks


def _tool_payload(res: Any) -> Any:
    assert isinstance(res, CallToolResult)
    content = res.content[0]
    assert isinstance(content, TextContent)
    return json.loads(content.text)


@pytest.fixture
def mock_client() -> AsyncMock:
    """Fixture providing an AsyncMock simulating AutomatedFanficClient."""
    client = AsyncMock(spec=AutomatedFanficClient)
    client.get_health.return_value = {"status": "ok"}
    client.get_coordinator.return_value = {
        "assignments": {"worker-1": "archiveofourown.org"}
    }
    client.get_queues.return_value = {"queued": [], "processing": [], "waiting": []}
    client.get_logs.return_value = {"items": [{"msg": "started"}]}
    client.get_story_diagnostics.return_value = {
        "url": "https://archiveofourown.org/works/123",
        "status": "ok",
    }
    client.get_calibre_book.return_value = {"found": True, "id": 123}
    client.get_antibot.return_value = {"flaresolverr": {"reachable": True}}
    client.get_cookiejar.return_value = {
        "domain": "archiveofourown.org",
        "cookies": [],
    }
    client.resolve_config.return_value = {"sections": ["defaults"]}
    client.run_diagnostic.return_value = {"status": "ok"}
    client.simulate_email.return_value = {"count": 1, "urls": ["https://ao3.org/1"]}
    client.dry_run.return_value = {"status": "ok", "title": "Test Fic"}
    client.add_url.return_value = {"accepted": True}
    client.cancel_url.return_value = {"ok": True}
    client.retry_now.return_value = {"ok": True}
    return client


@pytest.mark.anyio
async def test_mcp_tools_registration(mock_client: AsyncMock):
    """Verify all 17 debugging and control tools are registered with schemas and descriptions."""
    server = create_mcp_server(mock_client)
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    expected_tools = {
        "get_system_overview",
        "inspect_coordinator_locks",
        "inspect_queues",
        "query_logs",
        "get_story_diagnostics",
        "inspect_calibre_book",
        "test_calibre_connection",
        "test_antibot_status",
        "inspect_cookiejar",
        "resolve_config_for_url",
        "test_email_connection",
        "test_notification",
        "simulate_email_parse",
        "dry_run_fanfic_url",
        "inject_download",
        "cancel_download",
        "retry_now",
    }

    assert expected_tools.issubset(tool_names)
    assert len(tools) == 17

    for tool in tools:
        assert tool.description, f"Tool {tool.name} missing docstring description"


@pytest.mark.anyio
async def test_system_tools_invocation(mock_client: AsyncMock):
    """Verify system overview and coordinator inspect tools."""
    server = create_mcp_server(mock_client)

    res = await server.call_tool("get_system_overview", {})
    payload = _tool_payload(res)
    assert payload == {"status": "ok"}
    mock_client.get_health.assert_awaited_once()

    res_coord = await server.call_tool("inspect_coordinator_locks", {})
    payload_coord = _tool_payload(res_coord)
    assert "assignments" in payload_coord
    mock_client.get_coordinator.assert_awaited_once()

    # Direct function calls
    direct_overview = await get_system_overview()
    assert direct_overview == {"status": "ok"}
    direct_locks = await inspect_coordinator_locks()
    assert "assignments" in direct_locks


@pytest.mark.anyio
async def test_queues_tools_invocation(mock_client: AsyncMock):
    """Verify queue inspection tool."""
    server = create_mcp_server(mock_client)

    res = await server.call_tool("inspect_queues", {})
    payload = _tool_payload(res)
    assert "queued" in payload
    mock_client.get_queues.assert_awaited_once()

    direct = await inspect_queues()
    assert "queued" in direct


@pytest.mark.anyio
async def test_logs_tools_invocation(mock_client: AsyncMock):
    """Verify logs query tool parameter passing."""
    server = create_mcp_server(mock_client)

    res = await server.call_tool(
        "query_logs",
        {"level": "DEBUG", "component": "worker", "search": "error", "limit": 25},
    )
    payload = _tool_payload(res)
    assert "items" in payload
    mock_client.get_logs.assert_awaited_with(
        level="DEBUG", component="worker", search="error", limit=25
    )

    # Direct invocation with defaults
    direct = await query_logs()
    assert "items" in direct
    mock_client.get_logs.assert_awaited_with(
        level="ALL", component="", search="", limit=50
    )


@pytest.mark.anyio
async def test_story_tools_invocation(mock_client: AsyncMock):
    """Verify story diagnostics tool."""
    server = create_mcp_server(mock_client)
    url = "https://archiveofourown.org/works/123"

    res = await server.call_tool("get_story_diagnostics", {"url": url})
    payload = _tool_payload(res)
    assert payload["status"] == "ok"
    mock_client.get_story_diagnostics.assert_awaited_with(url=url)

    direct = await get_story_diagnostics(url=url)
    assert direct["status"] == "ok"


@pytest.mark.anyio
async def test_calibre_tools_invocation(mock_client: AsyncMock):
    """Verify calibre book lookup and connection test tools."""
    server = create_mcp_server(mock_client)

    res_book = await server.call_tool("inspect_calibre_book", {"query": "123"})
    payload_book = _tool_payload(res_book)
    assert payload_book["found"] is True
    mock_client.get_calibre_book.assert_awaited_with(query="123")

    res_conn = await server.call_tool("test_calibre_connection", {})
    payload_conn = _tool_payload(res_conn)
    assert payload_conn["status"] == "ok"
    mock_client.run_diagnostic.assert_awaited_with("calibre")

    direct_book = await inspect_calibre_book("123")
    assert direct_book["found"] is True
    direct_conn = await test_calibre_connection()
    assert direct_conn["status"] == "ok"


@pytest.mark.anyio
async def test_antibot_tools_invocation(mock_client: AsyncMock):
    """Verify antibot solver status and cookiejar inspect tools."""
    server = create_mcp_server(mock_client)

    res_bot = await server.call_tool("test_antibot_status", {})
    payload_bot = _tool_payload(res_bot)
    assert "flaresolverr" in payload_bot
    mock_client.get_antibot.assert_awaited_once()

    res_jar = await server.call_tool(
        "inspect_cookiejar", {"domain": "archiveofourown.org"}
    )
    payload_jar = _tool_payload(res_jar)
    assert payload_jar["domain"] == "archiveofourown.org"
    mock_client.get_cookiejar.assert_awaited_with(domain="archiveofourown.org")

    direct_bot = await test_antibot_status()
    assert "flaresolverr" in direct_bot
    direct_jar = await inspect_cookiejar("archiveofourown.org")
    assert direct_jar["domain"] == "archiveofourown.org"


@pytest.mark.anyio
async def test_config_tools_invocation(mock_client: AsyncMock):
    """Verify config resolution tool."""
    server = create_mcp_server(mock_client)
    url = "https://archiveofourown.org/works/123"

    res = await server.call_tool("resolve_config_for_url", {"url": url})
    payload = _tool_payload(res)
    assert "sections" in payload
    mock_client.resolve_config.assert_awaited_with(url=url)

    direct = await resolve_config_for_url(url=url)
    assert "sections" in direct


@pytest.mark.anyio
async def test_diagnostics_tools_invocation(mock_client: AsyncMock):
    """Verify diagnostics, email simulation, and dry run tools."""
    server = create_mcp_server(mock_client)

    # test_email_connection
    res_email = await server.call_tool("test_email_connection", {})
    payload_email = _tool_payload(res_email)
    assert payload_email["status"] == "ok"
    mock_client.run_diagnostic.assert_awaited_with("email")

    # test_notification
    res_notif = await server.call_tool(
        "test_notification", {"title": "Hello", "body": "World"}
    )
    payload_notif = _tool_payload(res_notif)
    assert payload_notif["status"] == "ok"
    mock_client.run_diagnostic.assert_awaited_with("notifications")

    # simulate_email_parse
    res_sim = await server.call_tool(
        "simulate_email_parse", {"subject": "Subj", "body": "Body text"}
    )
    payload_sim = _tool_payload(res_sim)
    assert payload_sim["count"] == 1
    mock_client.simulate_email.assert_awaited_with(subject="Subj", body="Body text")

    # dry_run_fanfic_url
    res_dry = await server.call_tool(
        "dry_run_fanfic_url", {"url": "https://archiveofourown.org/works/123"}
    )
    payload_dry = _tool_payload(res_dry)
    assert payload_dry["title"] == "Test Fic"
    mock_client.dry_run.assert_awaited_with(url="https://archiveofourown.org/works/123")

    # Direct invocations
    direct_email = await test_email_connection()
    assert direct_email["status"] == "ok"
    direct_notif = await test_notification()
    assert direct_notif["status"] == "ok"
    direct_sim = await simulate_email_parse("S", "B")
    assert direct_sim["count"] == 1
    direct_dry = await dry_run_fanfic_url("https://archiveofourown.org/works/123")
    assert direct_dry["title"] == "Test Fic"


@pytest.mark.anyio
async def test_controls_tools_invocation(mock_client: AsyncMock):
    """Verify download injection, cancellation, and retry controls tools."""
    server = create_mcp_server(mock_client)
    url = "https://archiveofourown.org/works/123"

    # inject_download
    res_inj = await server.call_tool("inject_download", {"url": url, "force": True})
    payload_inj = _tool_payload(res_inj)
    assert payload_inj["accepted"] is True
    mock_client.add_url.assert_awaited_with(url=url, force=True)

    # cancel_download
    res_canc = await server.call_tool("cancel_download", {"url": url})
    payload_canc = _tool_payload(res_canc)
    assert payload_canc["ok"] is True
    mock_client.cancel_url.assert_awaited_with(url=url)

    # retry_now
    res_ret = await server.call_tool("retry_now", {"url": url})
    payload_ret = _tool_payload(res_ret)
    assert payload_ret["ok"] is True
    mock_client.retry_now.assert_awaited_with(url=url)

    # Direct invocations
    direct_inj = await inject_download(url=url)
    assert direct_inj["accepted"] is True
    direct_canc = await cancel_download(url=url)
    assert direct_canc["ok"] is True
    direct_ret = await retry_now(url=url)
    assert direct_ret["ok"] is True


@pytest.mark.anyio
async def test_client_fallback_to_default(mock_client: AsyncMock):
    """Verify get_client falls back to _default_client when ContextVar is unset."""
    set_client(mock_client)
    _current_client.set(None)
    assert get_client() is mock_client


@pytest.mark.anyio
async def test_client_not_configured_raises():
    """Verify calling tool without configured client raises descriptive RuntimeError."""
    set_client(None)  # Reset client
    with pytest.raises(
        RuntimeError, match="No AutomatedFanficClient configured for MCP tools"
    ):
        get_client()
