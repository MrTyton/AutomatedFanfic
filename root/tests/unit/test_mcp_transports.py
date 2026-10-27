"""Unit tests for FastMCP transports (CLI Stdio & FastAPI SSE Mount)."""

import runpy
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import ASGITransport, AsyncClient
import pytest

from mcp_server.cli import main, run_cli
from web.dependencies import WebState
from web.server import create_app


@pytest.mark.anyio
async def test_mcp_sse_route_mounted():
    """Verify the MCP SSE endpoint is mounted at /api/mcp/sse and does not 404."""
    state = WebState()
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/mcp/sse")
        # SSE endpoint should return 200 or 400 (if SSE headers missing), but NOT 404
        assert resp.status_code in (200, 400)


@pytest.mark.anyio
async def test_mcp_sse_route_missing_accept_header():
    """Verify GET /api/mcp/sse without Accept: text/event-stream returns 400."""
    state = WebState()
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/mcp/sse")
        assert resp.status_code == 400
        assert "Accept" in resp.text or "event-stream" in resp.text


def test_mcp_cli_default_url(monkeypatch: pytest.MonkeyPatch):
    """Verify CLI reads default API URL if AUTOMATEDFANFIC_API_URL is unset."""
    monkeypatch.delenv("AUTOMATEDFANFIC_API_URL", raising=False)
    with (
        patch("mcp_server.cli.AutomatedFanficClient") as mock_client_cls,
        patch("mcp_server.cli.create_mcp_server") as mock_create_server,
    ):
        mock_client = MagicMock()
        mock_client.get_health.return_value = {"status": "ok"}
        mock_client_cls.from_url.return_value = mock_client
        mock_server = MagicMock()
        mock_create_server.return_value = mock_server

        exit_code = run_cli(check_connection=False)
        assert exit_code == 0
        mock_client_cls.from_url.assert_called_once_with("http://localhost:8080")
        mock_server.run.assert_called_once_with(transport="stdio")


def test_mcp_cli_custom_url(monkeypatch: pytest.MonkeyPatch):
    """Verify CLI respects custom AUTOMATEDFANFIC_API_URL environment variable."""
    monkeypatch.setenv("AUTOMATEDFANFIC_API_URL", "http://fanfic-box:9090")
    with (
        patch("mcp_server.cli.AutomatedFanficClient") as mock_client_cls,
        patch("mcp_server.cli.create_mcp_server") as mock_create_server,
    ):
        mock_client = MagicMock()
        mock_client_cls.from_url.return_value = mock_client
        mock_server = MagicMock()
        mock_create_server.return_value = mock_server

        exit_code = run_cli(check_connection=False)
        assert exit_code == 0
        mock_client_cls.from_url.assert_called_once_with("http://fanfic-box:9090")
        mock_server.run.assert_called_once_with(transport="stdio")


def test_mcp_cli_async_health_check():
    """Verify run_cli resolves async coroutine when checking health."""
    with (
        patch("mcp_server.cli.AutomatedFanficClient") as mock_client_cls,
        patch("mcp_server.cli.create_mcp_server") as mock_create_server,
    ):
        mock_client = MagicMock()
        mock_client.get_health = AsyncMock(return_value={"status": "ok"})
        mock_client_cls.from_url.return_value = mock_client
        mock_server = MagicMock()
        mock_create_server.return_value = mock_server

        exit_code = run_cli(check_connection=True)
        assert exit_code == 0
        mock_client.get_health.assert_awaited_once()
        mock_server.run.assert_called_once_with(transport="stdio")


def test_mcp_cli_offline_fallback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Verify CLI reports helpful guidance mentioning web.enabled when server is unreachable."""
    monkeypatch.setenv("AUTOMATEDFANFIC_API_URL", "http://localhost:8080")
    with (
        patch("mcp_server.cli.AutomatedFanficClient") as mock_client_cls,
        patch("mcp_server.cli.create_mcp_server"),
    ):
        mock_client = MagicMock()
        mock_client.get_health.side_effect = ConnectionRefusedError(
            "Connection refused"
        )
        mock_client_cls.from_url.return_value = mock_client

        exit_code = run_cli(check_connection=True)
        assert exit_code != 0
        captured = capsys.readouterr()
        assert "web.enabled" in captured.err


def test_mcp_cli_server_run_connection_error(
    capsys: pytest.CaptureFixture[str],
):
    """Verify run_cli catches connection errors raised while server is running."""
    with (
        patch("mcp_server.cli.AutomatedFanficClient") as mock_client_cls,
        patch("mcp_server.cli.create_mcp_server") as mock_create_server,
    ):
        mock_client = MagicMock()
        mock_client_cls.from_url.return_value = mock_client
        mock_server = MagicMock()
        mock_server.run.side_effect = ConnectionResetError("Reset by peer")
        mock_create_server.return_value = mock_server

        exit_code = run_cli(check_connection=False)
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "web.enabled" in captured.err


def test_mcp_cli_main_wrapper():
    """Verify main() entrypoint delegates to run_cli and handles sys.exit."""
    with (
        patch("mcp_server.cli.run_cli", return_value=0) as mock_run_cli,
        patch("sys.exit") as mock_exit,
    ):
        main()
        mock_run_cli.assert_called_once()
        mock_exit.assert_called_once_with(0)


def test_mcp_server_module_main():
    """Verify running mcp_server as module invokes cli.main."""
    with patch("mcp_server.cli.main") as mock_main:
        runpy.run_module("mcp_server", run_name="__main__")
        mock_main.assert_called_once()
