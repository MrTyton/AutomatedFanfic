"""Unit tests for debug REST API routes covering anti-bot, cookiejar, diagnostics, and force task controls."""

from http.cookiejar import Cookie, LWPCookieJar
import os
from pathlib import Path
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

from httpx import ASGITransport, AsyncClient
import pytest

from models.config_models import AppConfig, AppriseConfig, CalibreConfig, EmailConfig
from models.fanfic_info import FanficInfo
from web.dependencies import WebState
from web.server import create_app


def _make_app_config(
    *,
    personal_ini: str = "",
    email_server: str = "",
    email_user: str = "",
    email_password: str = "",
    email_mailbox: str = "INBOX",
    apprise_urls: list[str] | None = None,
    metadata_preservation_mode: Any = "preserve_metadata",
    update_method: Any = "update",
) -> AppConfig:
    return AppConfig(
        email=EmailConfig(
            server=email_server or "imap.example.com",
            email=email_user or "user@example.com",
            password=email_password or "password123",
            mailbox=email_mailbox,
        ),
        calibre=CalibreConfig(
            path="/fake/calibre/library",
            personal_ini=personal_ini or None,
            metadata_preservation_mode=metadata_preservation_mode,
            update_method=update_method,
        ),
        apprise=AppriseConfig(urls=apprise_urls or []),
    )


@pytest.mark.anyio
async def test_antibot_anubis_and_flaresolverr_diagnostic():
    state = WebState()
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/antibot")
        assert resp.status_code == 200
        data = resp.json()
        assert "flaresolverr" in data
        assert "anubis" in data
        assert data["anubis"]["ready"] is True
        assert data["flaresolverr"]["configured"] is False


@pytest.mark.anyio
async def test_antibot_flaresolverr_configured_and_reachable():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ini_path = os.path.join(tmp_dir, "personal.ini")
        Path(ini_path).write_text(
            "[defaults]\nflaresolverr_proxy: http://localhost:8191/v1\n",
            encoding="utf-8",
        )
        cfg = _make_app_config(personal_ini=ini_path)
        state = WebState(config=cfg)
        app = create_app(state)

        with patch(
            "web.routes.debug._check_flaresolverr_reachable",
            return_value={
                "configured": True,
                "endpoint": "http://localhost:8191/v1",
                "reachable": True,
                "latency_ms": 15.0,
                "error": None,
            },
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/debug/antibot")
                assert resp.status_code == 200
                data = resp.json()
                assert data["flaresolverr"]["configured"] is True
                assert data["flaresolverr"]["endpoint"] == "http://localhost:8191/v1"
                assert data["flaresolverr"]["reachable"] is True


@pytest.mark.anyio
async def test_controls_add_url_accepts_force_flag():
    mock_queue = MagicMock()
    active_urls: Any = {}
    state = WebState(ingress_queue=mock_queue, active_urls=active_urls)
    app = create_app(state)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/controls/add-url",
            json={"url": "https://archiveofourown.org/works/123", "force": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is True
        assert mock_queue.put.called
        enqueued_fanfic = mock_queue.put.call_args[0][0]
        assert isinstance(enqueued_fanfic, FanficInfo)
        assert enqueued_fanfic.behavior == "force"


@pytest.mark.anyio
async def test_controls_add_url_default_force_is_false():
    mock_queue = MagicMock()
    active_urls: Any = {}
    state = WebState(ingress_queue=mock_queue, active_urls=active_urls)
    app = create_app(state)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/controls/add-url",
            json={"url": "https://archiveofourown.org/works/456"},
        )
        assert resp.status_code == 200
        enqueued_fanfic = mock_queue.put.call_args[0][0]
        assert isinstance(enqueued_fanfic, FanficInfo)
        assert enqueued_fanfic.behavior in (None, "update")


@pytest.mark.anyio
async def test_cookiejar_not_found_returns_clean_payload():
    """Review Focus #2: Returns 200 with empty list and file_path None without crashing."""
    state = WebState()
    app = create_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/debug/cookiejar/archiveofourown.org")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {
            "domain": "archiveofourown.org",
            "cookie_count": 0,
            "cookies": [],
            "file_path": None,
            "message": "No cookiejar found",
        }


@pytest.mark.anyio
async def test_cookiejar_existing_file_inspects_and_masks_tokens():
    with tempfile.TemporaryDirectory() as tmp_dir:
        cookie_file = os.path.join(tmp_dir, "ao3_cookies.txt")
        jar = LWPCookieJar(cookie_file)
        c = Cookie(
            version=0,
            name="_otw_session",
            value="super_secret_session_token_12345",
            port=None,
            port_specified=False,
            domain=".archiveofourown.org",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=1893456000,
            discard=False,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": ""},
        )
        jar.set_cookie(c)
        jar.save(ignore_discard=True, ignore_expires=True)

        ini_path = os.path.join(tmp_dir, "personal.ini")
        Path(ini_path).write_text(
            f"[archiveofourown.org]\ncookiejar: {cookie_file}\n",
            encoding="utf-8",
        )

        cfg = _make_app_config(personal_ini=ini_path)
        state = WebState(config=cfg)
        app = create_app(state)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/debug/cookiejar/archiveofourown.org")
            assert resp.status_code == 200
            data = resp.json()
            assert data["domain"] == "archiveofourown.org"
            assert data["cookie_count"] == 1
            assert len(data["cookies"]) == 1
            cookie_data = data["cookies"][0]
            assert cookie_data["name"] == "_otw_session"
            assert "super_secret_session_token_12345" not in cookie_data["value"]
            assert cookie_data["value"].startswith("sup...")
            assert cookie_data["expires"] == 1893456000


@pytest.mark.anyio
async def test_resolve_config_endpoint():
    cfg = _make_app_config(
        metadata_preservation_mode="preserve_metadata", update_method="update"
    )
    state = WebState(config=cfg)
    app = create_app(state)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/debug/resolve-config",
            json={"url": "https://archiveofourown.org/works/123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "https://archiveofourown.org/works/123"
        assert "ArchiveOfOurOwn" in data["adapter"]
        assert "calibre_strategy" in data
        assert (
            data["calibre_strategy"]["metadata_preservation_mode"]
            == "preserve_metadata"
        )
        assert data["calibre_strategy"]["update_method"] == "update"
        assert "options" in data


@pytest.mark.anyio
async def test_diagnostics_service_calibre():
    mock_calibre = MagicMock()
    mock_calibre.get_version.return_value = "7.2.0"
    state = WebState()
    app = create_app(state)
    app.state.calibre_client = mock_calibre

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/debug/diagnostics/calibre")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "calibre"
        assert data["status"] == "ok"
        assert data["details"]["version"] == "7.2.0"


@pytest.mark.anyio
async def test_diagnostics_service_fanficfare():
    state = WebState()
    app = create_app(state)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/debug/diagnostics/fanficfare")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "fanficfare"
        assert data["status"] == "ok"
        assert "version" in data["details"]


@pytest.mark.anyio
async def test_diagnostics_service_email():
    cfg = _make_app_config(
        email_server="imap.example.com",
        email_user="reader@example.com",
        email_password="secret",
        email_mailbox="Fanfiction",
    )
    state = WebState(config=cfg)
    app = create_app(state)

    with patch("imaplib.IMAP4_SSL") as mock_imap:
        instance = MagicMock()
        mock_imap.return_value = instance
        instance.login.return_value = ("OK", [b"Logged in"])
        instance.select.return_value = ("OK", [b"42"])
        instance.search.return_value = ("OK", [b"1 2 3"])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/debug/diagnostics/email")
            data = resp.json()
            assert resp.status_code == 200
            assert data["service"] == "email"
            assert data["status"] == "ok"
            assert data["details"]["unread_count"] == 3


@pytest.mark.anyio
async def test_diagnostics_service_notifications():
    cfg = _make_app_config(apprise_urls=["pbul://access_token"])
    state = WebState(config=cfg)
    app = create_app(state)

    with patch(
        "notifications.apprise_notification.AppriseNotification.send_notification",
        return_value=True,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/debug/diagnostics/notifications")
            data = resp.json()
            assert resp.status_code == 200
            assert data["service"] == "notifications"
            assert data["status"] == "ok"


@pytest.mark.anyio
async def test_diagnostics_service_unknown_returns_400():
    state = WebState()
    app = create_app(state)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/debug/diagnostics/nonexistent_service")
        assert resp.status_code == 400


@pytest.mark.anyio
async def test_dry_run_endpoint():
    state = WebState()
    app = create_app(state)

    mock_adapter = MagicMock()
    mock_adapter.getSiteDomain.return_value = "archiveofourown.org"
    mock_adapter.getMetadata.side_effect = lambda key: (
        "Test Fanfiction Title" if key == "title" else "Author Name"
    )
    mock_adapter.num_chapters.return_value = 5

    with patch("fanficfare.adapters.getAdapter", return_value=mock_adapter):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/debug/dry-run",
                json={"url": "https://archiveofourown.org/works/12345"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["title"] == "Test Fanfiction Title"
            assert data["author"] == "Author Name"
            assert data["chapters"] == 5
            assert data["site"] == "archiveofourown.org"


@pytest.mark.anyio
async def test_simulate_email_endpoint():
    state = WebState()
    app = create_app(state)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/debug/simulate-email",
            json={
                "subject": "New chapter posted for story",
                "body": "Read it here: https://archiveofourown.org/works/98765432 and enjoy!",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        assert any("98765432" in match["url"] for match in data["matches"])
