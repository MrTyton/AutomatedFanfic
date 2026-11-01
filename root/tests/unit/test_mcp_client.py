"""Unit tests for AutomatedFanficClient and FastMCP server core."""

from queue import Queue
from unittest.mock import MagicMock, patch
import httpx
import pytest

from mcp_server.client import AutomatedFanficClient
from mcp_server.server import FastMCP, create_mcp_server
from web.dependencies import WebState
from web.server import create_app


@pytest.mark.anyio
async def test_mcp_client_asgi_transport():
    """Verify AutomatedFanficClient.from_app initializes with ASGITransport and hits health endpoint."""
    state = WebState()
    app = create_app(state)
    client = AutomatedFanficClient.from_app(app)
    health = await client.get_health()
    assert health == {"status": "ok"}
    await client.close()


@pytest.mark.anyio
async def test_mcp_client_context_manager():
    """Verify AutomatedFanficClient can be used as an async context manager."""
    state = WebState()
    app = create_app(state)
    async with AutomatedFanficClient.from_app(app) as client:
        health = await client.get_health()
        assert health == {"status": "ok"}


def test_mcp_client_from_url_default():
    """Verify AutomatedFanficClient.from_url sets default base_url."""
    client = AutomatedFanficClient.from_url()
    assert client.base_url == "http://localhost:8080"


@pytest.mark.anyio
async def test_mcp_client_connection_error_handling():
    """Verify connection errors return informative error dicts instead of raising."""
    client = AutomatedFanficClient.from_url(base_url="http://127.0.0.1:9999")
    with patch.object(
        client._client,
        "request",
        side_effect=httpx.ConnectError("Connection refused"),
    ):
        res = await client.get_health()
        assert res["ok"] is False
        assert "not reachable" in res["error"]
        assert "http://127.0.0.1:9999" in res["error"]
    await client.close()


@pytest.mark.anyio
async def test_mcp_client_network_error_handling():
    """Verify network errors return informative error dicts instead of raising."""
    client = AutomatedFanficClient.from_url(base_url="http://127.0.0.1:8080")
    with patch.object(
        client._client,
        "request",
        side_effect=httpx.NetworkError("Network unreachable"),
    ):
        res = await client.get_queues()
        assert res["ok"] is False
        assert "not reachable" in res["error"]
    await client.close()


@pytest.mark.anyio
async def test_mcp_client_endpoints_asgi():
    """Verify all client query and mutation methods against real FastAPI routes."""
    mock_ingress = Queue()
    mock_waiting = Queue()
    state = WebState(
        ingress_queue=mock_ingress,
        waiting_queue=mock_waiting,
        active_urls={
            "https://archiveofourown.org/works/123": {
                "status": "processing",
                "site": "archiveofourown.org",
            }
        },
        coordinator_status={
            "assignments": {"worker-1": "archiveofourown.org"},
            "idle_workers": [],
            "dormant_workers": [],
            "backlog": {},
        },
    )
    app = create_app(state)

    async with AutomatedFanficClient.from_app(app) as client:
        # Queues inspect
        queues = await client.get_queues()
        assert "processing" in queues
        assert len(queues["processing"]) == 1

        # Coordinator inspect
        coord = await client.get_coordinator()
        assert "assignments" in coord
        assert coord["assignments"]["worker-1"] == "archiveofourown.org"

        # Logs
        logs = await client.get_logs(
            level="ALL", component="worker", search="processing", limit=10
        )
        assert "items" in logs

        # Story diagnostics
        diag = await client.get_story_diagnostics(
            "https://archiveofourown.org/works/123"
        )
        assert diag["url"] == "https://archiveofourown.org/works/123"
        assert diag["active_state"]["status"] == "processing"

        # Calibre book inspect (without Calibre configured)
        calibre_book = await client.get_calibre_book("123")
        assert calibre_book["found"] is False

        # Anti-bot
        antibot = await client.get_antibot()
        assert "flaresolverr" in antibot
        assert "anubis" in antibot

        # Cookiejar inspect
        jar = await client.get_cookiejar("archiveofourown.org")
        assert jar["domain"] == "archiveofourown.org"

        # Resolve config
        conf = await client.resolve_config("https://archiveofourown.org/works/123")
        assert "sections" in conf

        # Diagnostics for calibre
        diag_res = await client.run_diagnostic("calibre")
        assert diag_res["service"] == "calibre"

        # Dry run
        mock_adapter = MagicMock()
        mock_adapter.getSiteDomain.return_value = "archiveofourown.org"
        mock_adapter.getMetadata.side_effect = lambda key: (
            "Test Fanfiction Title" if key == "title" else "Author Name"
        )
        mock_adapter.num_chapters.return_value = 5
        with patch("fanficfare.adapters.getAdapter", return_value=mock_adapter):
            dry = await client.dry_run("https://archiveofourown.org/works/123")
            assert dry["status"] == "ok"
            assert dry["title"] == "Test Fanfiction Title"

        # Simulate email
        sim = await client.simulate_email(
            "New fic notification",
            "Read at https://archiveofourown.org/works/123 now!",
        )
        assert sim["count"] >= 1

        # Add URL
        add_res = await client.add_url(
            "https://archiveofourown.org/works/456", force=True
        )
        assert "accepted" in add_res

        # Cancel URL
        cancel_res = await client.cancel_url("https://archiveofourown.org/works/123")
        assert "ok" in cancel_res

        # Retry now
        retry_res = await client.retry_now("https://archiveofourown.org/works/123")
        assert "ok" in retry_res


@pytest.mark.anyio
async def test_mcp_client_properties():
    """Verify base_url and client properties."""
    client = AutomatedFanficClient.from_url("http://127.0.0.1:8080/")
    assert client.base_url == "http://127.0.0.1:8080"
    assert isinstance(client.client, httpx.AsyncClient)
    await client.close()


@pytest.mark.anyio
async def test_mcp_client_generic_request_error():
    """Verify generic RequestError handling."""
    client = AutomatedFanficClient.from_url()
    with patch.object(
        client._client,
        "request",
        side_effect=httpx.RequestError("Protocol error"),
    ):
        res = await client.get_health()
        assert res["ok"] is False
        assert "Request to AutomatedFanfic web server failed" in res["error"]
    await client.close()


@pytest.mark.anyio
async def test_mcp_client_response_edge_cases():
    """Verify JSON parsing and status code edge cases."""
    client = AutomatedFanficClient.from_url()

    # 1. 200 OK with list JSON
    mock_resp_list = MagicMock()
    mock_resp_list.status_code = 200
    mock_resp_list.json.return_value = ["item1", "item2"]
    with patch.object(client._client, "request", return_value=mock_resp_list):
        res = await client.get_health()
        assert res == {"result": ["item1", "item2"]}

    # 2. 200 OK with malformed JSON
    mock_resp_malformed = MagicMock()
    mock_resp_malformed.status_code = 200
    mock_resp_malformed.json.side_effect = ValueError("Bad JSON")
    with patch.object(client._client, "request", return_value=mock_resp_malformed):
        res = await client.get_health()
        assert res["ok"] is False
        assert "Invalid JSON response" in res["error"]

    # 3. 404 with JSON dict
    mock_resp_404_json = MagicMock()
    mock_resp_404_json.status_code = 404
    mock_resp_404_json.json.return_value = {"detail": "Not found"}
    with patch.object(client._client, "request", return_value=mock_resp_404_json):
        res = await client.get_health()
        assert res == {"detail": "Not found"}

    # 4. 500 with non-JSON plain text
    mock_resp_500_text = MagicMock()
    mock_resp_500_text.status_code = 500
    mock_resp_500_text.json.side_effect = ValueError("Not JSON")
    mock_resp_500_text.text = "Internal Server Error"
    with patch.object(client._client, "request", return_value=mock_resp_500_text):
        res = await client.get_health()
        assert res["ok"] is False
        assert res["status_code"] == 500
        assert res["error"] == "Internal Server Error"

    # 5. 400 with non-dict JSON (e.g. string)
    mock_resp_400_str = MagicMock()
    mock_resp_400_str.status_code = 400
    mock_resp_400_str.json.return_value = "Bad request text"
    with patch.object(client._client, "request", return_value=mock_resp_400_str):
        res = await client.get_health()
        assert res["ok"] is False
        assert res["status_code"] == 400
        assert res["error"] == "Bad request text"

    await client.close()


@pytest.mark.anyio
async def test_create_mcp_server():
    """Verify create_mcp_server returns a FastMCP/MCPServer instance with client attached."""
    client = AutomatedFanficClient.from_url()
    server = create_mcp_server(client)
    assert isinstance(server, FastMCP)
    assert server.name == "AutomatedFanfic"
    assert getattr(server, "client") is client
    tools = await server.list_tools()
    assert isinstance(tools, list)
    await client.close()


@pytest.mark.anyio
async def test_mcp_client_expanded_endpoints():
    client = AutomatedFanficClient.from_url()

    # 1. get_system_status
    with patch.object(client, "_request") as mock_req:
        mock_req.side_effect = [
            {"status": "ok"},
            {"automatedfanfic": "6.15.14"},
            {"queues": {}, "workers": {}},
        ]
        status = await client.get_system_status()
        assert status["health"] == {"status": "ok"}
        assert status["version"]["automatedfanfic"] == "6.15.14"
        assert "queues" in status["status"]
        assert mock_req.call_count == 3

    # 2. get_story_history
    with patch.object(client, "_request", return_value={"found": True}) as mock_req:
        res = await client.get_story_history("https://ao3.org/123")
        assert res["found"] is True
        mock_req.assert_called_once_with(
            "GET", "/api/history/story", params={"url": "https://ao3.org/123"}
        )

    # 3. get_downloads
    with patch.object(client, "_request", return_value={"items": []}) as mock_req:
        res = await client.get_downloads(
            search="bard", site="ffnet", status="success", limit=10, offset=5
        )
        assert res["items"] == []
        mock_req.assert_called_once_with(
            "GET",
            "/api/history/downloads",
            params={
                "limit": 10,
                "offset": 5,
                "search": "bard",
                "site": "ffnet",
                "status": "success",
            },
        )

    # 4. get_retries
    with patch.object(client, "_request", return_value={"items": []}) as mock_req:
        res = await client.get_retries(search="bard", site="ffnet", limit=20)
        assert res["items"] == []
        mock_req.assert_called_once_with(
            "GET",
            "/api/history/retries",
            params={"limit": 20, "offset": 0, "search": "bard", "site": "ffnet"},
        )

    # 5. get_email_history
    with patch.object(client, "_request", return_value={"items": []}) as mock_req:
        res = await client.get_email_history(limit=15, offset=2)
        assert res["items"] == []
        mock_req.assert_called_once_with(
            "GET", "/api/history/emails", params={"limit": 15, "offset": 2}
        )

    # 6. get_notification_history
    with patch.object(client, "_request", return_value={"items": []}) as mock_req:
        res = await client.get_notification_history(
            search="alert", site="ao3", limit=30
        )
        assert res["items"] == []
        mock_req.assert_called_once_with(
            "GET",
            "/api/history/notifications",
            params={"limit": 30, "offset": 0, "search": "alert", "site": "ao3"},
        )

    # 7. get_config
    with patch.object(
        client, "_request", return_value={"config": {"retry": {"max_retries": 11}}}
    ) as mock_req:
        res = await client.get_config()
        assert "config" in res
        res_sec = await client.get_config(section="retry")
        assert res_sec == {"section": "retry", "values": {"max_retries": 11}}

    # 8. get_ini_file
    with patch.object(
        client, "_request", return_value={"content": "[defaults]"}
    ) as mock_req:
        res = await client.get_ini_file("personal")
        assert res["content"] == "[defaults]"
        mock_req.assert_called_once_with("GET", "/api/config/ini/personal")

    # 9. trigger_email_check
    with patch.object(client, "_request", return_value={"ok": True}) as mock_req:
        res = await client.trigger_email_check()
        assert res["ok"] is True
        mock_req.assert_called_once_with("POST", "/api/controls/check-emails")

    # 10. restart_daemon
    with patch.object(client, "_request", return_value={"ok": True}) as mock_req:
        res = await client.restart_daemon("ao3-worker")
        assert res["ok"] is True
        mock_req.assert_called_once_with(
            "POST", "/api/controls/restart-daemon", json={"name": "ao3-worker"}
        )

    # 11. retry_all_waiting
    with patch.object(client, "_request", return_value={"ok": True}) as mock_req:
        res = await client.retry_all_waiting()
        assert res["ok"] is True
        mock_req.assert_called_once_with("POST", "/api/controls/retry-all")

    # 12. toggle_site
    with patch.object(client, "_request", return_value={"ok": True}) as mock_req:
        res = await client.toggle_site("archiveofourown")
        assert res["ok"] is True
        mock_req.assert_called_once_with(
            "POST", "/api/controls/toggle-site", json={"site": "archiveofourown"}
        )

    # 13. redownload_scratch
    with patch.object(client, "_request", return_value={"ok": True}) as mock_req:
        res = await client.redownload_scratch("https://ao3.org/123")
        assert res["ok"] is True
        mock_req.assert_called_once_with(
            "POST",
            "/api/controls/redownload-scratch",
            json={"url": "https://ao3.org/123"},
        )

    # 14. recover_flaresolverr
    with patch.object(
        client, "_request", return_value={"ok": True, "recovered": 1}
    ) as mock_req:
        res = await client.recover_flaresolverr("royalroad")
        assert res["recovered"] == 1
        mock_req.assert_called_once_with(
            "POST", "/api/debug/flaresolverr/recover", json={"target_site": "royalroad"}
        )

    await client.close()
