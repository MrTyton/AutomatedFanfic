"""
Generic browser impersonation session for FanFicFare.

Replaces standard Python OpenSSL / urllib3 transport in FanFicFare's RequestsFetcher
with curl-cffi Chrome impersonation (HTTP/2, HTTP/3, JA3/JA4 TLS fingerprinting).
This prevents Cloudflare HTTP 525 ("SSL Handshake Failed") errors and 403 Forbidden
challenges generically across all supported sites without requiring manual cookie
exports or site-specific hacks.
"""

from collections.abc import Mapping
from http.cookiejar import CookieJar
from typing import Any
import requests
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError as RequestsHTTPError,
    RequestException as RequestsRequestException,
    Timeout as RequestsTimeout,
)
from requests_file import FileAdapter

try:
    from curl_cffi import requests as cffi_requests
    from curl_cffi.requests.exceptions import (
        ConnectionError as CffiConnectionError,
        RequestException as CffiRequestException,
        Timeout as CffiTimeout,
    )

    CURL_CFFI_AVAILABLE = True
except ImportError:  # pragma: no cover
    cffi_requests = None  # type: ignore[assignment]
    CffiConnectionError = None  # type: ignore[assignment]
    CffiRequestException = None  # type: ignore[assignment]
    CffiTimeout = None  # type: ignore[assignment]
    CURL_CFFI_AVAILABLE = False

lazy from fanficfare.fetchers import fetcher_requests as fff_fetcher_requests
from utils import ff_logging

_ORIGINAL_MAKE_SESSION = fff_fetcher_requests.RequestsFetcher.make_sesssion
_ORIGINAL_DO_MOUNTS = fff_fetcher_requests.RequestsFetcher.do_mounts
_IS_INSTALLED = False


class ImpersonatedResponse:
    """Wrapper around curl_cffi Response matching the requests.Response contract."""

    def __init__(self, raw_resp: Any) -> None:
        self._raw = raw_resp
        self.status_code: int = raw_resp.status_code
        self.content: bytes = raw_resp.content
        self.text: str = raw_resp.text
        self.url: str = raw_resp.url
        self.headers: Any = raw_resp.headers
        self.cookies: Any = raw_resp.cookies

    def json(self, **kwargs: Any) -> Any:
        """Parse response JSON payload."""
        return self._raw.json(**kwargs)

    def raise_for_status(self) -> None:
        """Raise standard requests.exceptions.HTTPError if response status indicates an error."""
        if 400 <= self.status_code < 600:
            error_type = "Client Error" if self.status_code < 500 else "Server Error"
            msg = f"{self.status_code} {error_type}: for url: {self.url}"
            raise RequestsHTTPError(msg, response=self)


class ImpersonatedSession:
    """
    Session conforming to requests.Session interface backed by curl-cffi Chrome impersonation.

    Routes HTTP/HTTPS requests through curl-cffi (HTTP/2, HTTP/3, Chrome TLS fingerprint),
    and delegates file:// URLs to a standard requests.Session with FileAdapter.
    """

    def __init__(self, impersonate: str = "chrome131") -> None:
        self.impersonate = impersonate
        if CURL_CFFI_AVAILABLE and cffi_requests is not None:
            self._cffi_session: Any = cffi_requests.Session(impersonate=impersonate)
        else:  # pragma: no cover
            self._cffi_session = None

        self._file_session = requests.Session()
        self._file_session.mount("file://", FileAdapter())
        self.headers: dict[str, str] = {}
        self.proxies: dict[str, str] = {}
        self._cookiejar: CookieJar | None = None

    @property
    def cookies(self) -> Any:
        """Return the current cookie collection."""
        if self._cookiejar is not None:
            return self._cookiejar
        if self._cffi_session is not None:
            return self._cffi_session.cookies
        return self._file_session.cookies

    @cookies.setter
    def cookies(self, jar: CookieJar) -> None:
        """Assign an external CookieJar to the session."""
        self._cookiejar = jar
        if self._cffi_session is not None:
            self._cffi_session.cookies = jar
        self._file_session.cookies = jar

    def mount(self, prefix: str, adapter: Any) -> None:
        """
        Mount a transport adapter.

        No-op for HTTP/HTTPS since curl-cffi handles connection pooling and modern TLS
        fingerprints internally. Mounts to file session if prefix is file://.
        """
        if prefix.startswith("file:"):
            self._file_session.mount(prefix, adapter)

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        data: Any = None,
        json: Any = None,
        verify: bool = True,
        timeout: float = 60.0,
        **kwargs: Any,
    ) -> Any:
        """
        Send a request using browser impersonation or file transport.

        Translates curl-cffi exceptions to standard requests exceptions so FanFicFare
        error handling and retries function identically.
        """
        if url.startswith("file://") or url.startswith("file:"):
            return self._file_session.request(
                method=method,
                url=url,
                headers=dict(headers) if headers is not None else None,
                data=data,
                json=json,
                verify=verify,
                timeout=timeout,
                **kwargs,
            )

        if not CURL_CFFI_AVAILABLE or self._cffi_session is None:  # pragma: no cover
            return self._file_session.request(
                method=method,
                url=url,
                headers=dict(headers) if headers is not None else None,
                data=data,
                json=json,
                verify=verify,
                timeout=timeout,
                **kwargs,
            )

        sanitized_headers: dict[str, str] = {}
        if self.headers:
            sanitized_headers.update(self.headers)
        if headers:
            sanitized_headers.update(headers)

        # Remove blank User-Agent headers that cause Cloudflare 403 blocks
        if sanitized_headers.get("User-Agent") == "":
            del sanitized_headers["User-Agent"]

        try:
            raw_resp = self._cffi_session.request(
                method=method,
                url=url,
                headers=sanitized_headers if sanitized_headers else None,
                data=data,
                json=json,
                verify=verify,
                timeout=timeout,
                proxies=self.proxies if self.proxies else None,
                **kwargs,
            )
            return ImpersonatedResponse(raw_resp)
        except CffiTimeout as e:
            raise RequestsTimeout(str(e)) from e
        except CffiConnectionError as e:
            raise RequestsConnectionError(str(e)) from e
        except CffiRequestException as e:
            raise RequestsRequestException(str(e)) from e

    def close(self) -> None:
        """Close underlying sessions."""
        if self._cffi_session is not None:
            self._cffi_session.close()
        self._file_session.close()


def install_impersonated_session() -> bool:
    """
    Configure FanFicFare's RequestsFetcher to use ImpersonatedSession generically.

    Returns True if curl-cffi is installed and active; False if falling back to requests.
    """
    global _IS_INSTALLED
    if not CURL_CFFI_AVAILABLE:  # pragma: no cover
        ff_logging.log_debug(
            "curl-cffi is not installed; FanFicFare using standard requests transport"
        )
        return False

    def _make_impersonated_session(self: Any) -> ImpersonatedSession:
        return ImpersonatedSession()

    def _do_impersonated_mounts(self: Any, session: Any) -> None:
        # FanFicFare configures proxies and file adapter through do_mounts
        session.mount("file://", FileAdapter())
        if self.getConfig("http_proxy"):
            session.proxies["http"] = self.getConfig("http_proxy")
        if self.getConfig("https_proxy"):
            session.proxies["https"] = self.getConfig("https_proxy")

    fff_fetcher_requests.RequestsFetcher.make_sesssion = _make_impersonated_session
    fff_fetcher_requests.RequestsFetcher.do_mounts = _do_impersonated_mounts
    _IS_INSTALLED = True
    ff_logging.log_debug(
        "Generic browser impersonation (curl-cffi) active for FanFicFare RequestsFetcher"
    )
    return True


def uninstall_impersonated_session() -> None:
    """Restore FanFicFare's RequestsFetcher to original make_sesssion / do_mounts implementations."""
    global _IS_INSTALLED
    fff_fetcher_requests.RequestsFetcher.make_sesssion = _ORIGINAL_MAKE_SESSION
    fff_fetcher_requests.RequestsFetcher.do_mounts = _ORIGINAL_DO_MOUNTS
    _IS_INSTALLED = False


def is_impersonated_session_installed() -> bool:
    """Check if the impersonated session hook is currently installed."""
    return _IS_INSTALLED
