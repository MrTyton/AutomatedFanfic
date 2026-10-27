"""
Unit tests for generic browser impersonation session.
"""

from http.cookiejar import Cookie, CookieJar
import tempfile
from unittest.mock import MagicMock, patch
import pytest
import requests
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError as RequestsHTTPError,
    RequestException as RequestsRequestException,
    Timeout as RequestsTimeout,
)

from fanficfare.fetchers import fetcher_requests as fff_fetcher_requests
from workers.impersonated_session import (
    ImpersonatedResponse,
    ImpersonatedSession,
    install_impersonated_session,
    is_impersonated_session_installed,
    uninstall_impersonated_session,
)


@pytest.fixture(autouse=True)
def cleanup_impersonated_session():
    """Ensure impersonated session hook is uninstalled before and after each test."""
    uninstall_impersonated_session()
    yield
    uninstall_impersonated_session()


class DummyRawResponse:
    """Mock raw response from curl_cffi."""

    def __init__(
        self,
        status_code: int = 200,
        content: bytes = b"test content",
        text: str = "test content",
        url: str = "https://example.com/test",
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.text = text
        self.url = url
        self.headers = {"Content-Type": "text/plain"}
        self.cookies = {"session": "abc123"}

    def json(self, **kwargs):
        if kwargs.get("fail"):
            raise ValueError("Invalid JSON")
        return {"key": "value"}


def test_impersonated_response_attributes():
    """Verify ImpersonatedResponse exposes standard requests response attributes."""
    raw = DummyRawResponse()
    resp = ImpersonatedResponse(raw)

    assert resp.status_code == 200
    assert resp.content == b"test content"
    assert resp.text == "test content"
    assert resp.url == "https://example.com/test"
    assert resp.headers == {"Content-Type": "text/plain"}
    assert resp.cookies == {"session": "abc123"}
    assert resp.json() == {"key": "value"}


def test_impersonated_response_raise_for_status_success():
    """Verify raise_for_status does not raise for 2xx or 3xx responses."""
    resp_200 = ImpersonatedResponse(DummyRawResponse(status_code=200))
    resp_200.raise_for_status()

    resp_302 = ImpersonatedResponse(DummyRawResponse(status_code=302))
    resp_302.raise_for_status()


def test_impersonated_response_raise_for_status_errors():
    """Verify raise_for_status raises standard requests.exceptions.HTTPError with response attached."""
    resp_404 = ImpersonatedResponse(DummyRawResponse(status_code=404))
    with pytest.raises(RequestsHTTPError) as exc_info:
        resp_404.raise_for_status()
    assert exc_info.value.response is not None
    assert exc_info.value.response.status_code == 404
    assert "404 Client Error" in str(exc_info.value)

    resp_525 = ImpersonatedResponse(DummyRawResponse(status_code=525))
    with pytest.raises(RequestsHTTPError) as exc_info:
        resp_525.raise_for_status()
    assert exc_info.value.response is not None
    assert exc_info.value.response.status_code == 525
    assert "525 Server Error" in str(exc_info.value)


def test_impersonated_session_cookies():
    """Verify CookieJar assignment and retrieval on ImpersonatedSession."""
    session = ImpersonatedSession()
    jar = CookieJar()
    cookie = Cookie(
        version=0,
        name="test_cookie",
        value="test_val",
        port=None,
        port_specified=False,
        domain=".example.com",
        domain_specified=True,
        domain_initial_dot=True,
        path="/",
        path_specified=True,
        secure=False,
        expires=None,
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
    )
    jar.set_cookie(cookie)

    session.cookies = jar
    assert session.cookies is jar


def test_impersonated_session_mount_noop():
    """Verify mount is safe for https:// and mounts file:// to internal file session."""
    session = ImpersonatedSession()
    # Should not raise for https:// or http://
    session.mount("https://", MagicMock())
    session.mount("http://", MagicMock())

    # FileAdapter should mount cleanly to file session
    mock_file_adapter = MagicMock()
    session.mount("file://", mock_file_adapter)


def test_impersonated_session_file_url():
    """Verify file:// URLs are routed through the internal file session."""
    session = ImpersonatedSession()
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(b"local file content")
        file_path = tf.name.replace("\\", "/")

    resp = session.request("GET", f"file:///{file_path}")
    assert resp.status_code == 200
    assert resp.content == b"local file content"
    session.close()


def test_impersonated_session_sanitizes_empty_user_agent():
    """Verify empty User-Agent headers are removed to prevent Cloudflare 403 blocks."""
    session = ImpersonatedSession()
    if session._cffi_session is not None:
        with patch.object(
            session._cffi_session, "request", return_value=DummyRawResponse()
        ) as mock_req:
            session.request(
                "GET",
                "https://example.com",
                headers={"User-Agent": "", "Accept": "text/html"},
            )
            call_headers = mock_req.call_args[1]["headers"]
            assert "User-Agent" not in call_headers
            assert call_headers["Accept"] == "text/html"


def test_impersonated_session_translates_exceptions():
    """Verify curl_cffi exceptions are translated into requests equivalents."""
    from curl_cffi.requests.exceptions import (
        ConnectionError as CffiConnError,
        RequestException as CffiReqError,
        Timeout as CffiTimeError,
    )

    session = ImpersonatedSession()
    if session._cffi_session is not None:
        with patch.object(
            session._cffi_session,
            "request",
            side_effect=CffiTimeError("timed out"),
        ):
            with pytest.raises(RequestsTimeout):
                session.request("GET", "https://example.com")

        with patch.object(
            session._cffi_session,
            "request",
            side_effect=CffiConnError("failed to connect"),
        ):
            with pytest.raises(RequestsConnectionError):
                session.request("GET", "https://example.com")

        with patch.object(
            session._cffi_session,
            "request",
            side_effect=CffiReqError("general curl error"),
        ):
            with pytest.raises(RequestsRequestException):
                session.request("GET", "https://example.com")


def test_install_and_uninstall_lifecycle():
    """Verify install_impersonated_session patches and uninstalls cleanly."""
    assert not is_impersonated_session_installed()

    installed = install_impersonated_session()
    assert installed is True
    assert is_impersonated_session_installed()

    # RequestsFetcher.make_sesssion should now return ImpersonatedSession
    fetcher = fff_fetcher_requests.RequestsFetcher(lambda k: None, lambda k: [])
    session = fetcher.make_sesssion()
    assert isinstance(session, ImpersonatedSession)

    # do_mounts should run without errors
    fetcher.do_mounts(session)

    # Uninstall should restore original behavior
    uninstall_impersonated_session()
    assert not is_impersonated_session_installed()
    restored_session = fetcher.make_sesssion()
    assert isinstance(restored_session, requests.Session)
    assert not isinstance(restored_session, ImpersonatedSession)


def test_fallback_when_curl_cffi_missing():
    """Verify fallback when curl-cffi is not available."""
    with patch("workers.impersonated_session.CURL_CFFI_AVAILABLE", False):
        result = install_impersonated_session()
        assert result is False
        assert not is_impersonated_session_installed()
