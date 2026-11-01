"""Asynchronous HTTP and ASGI client for AutomatedFanfic web and debug endpoints."""

import types
from typing import Any
from fastapi import FastAPI
import httpx


class AutomatedFanficClient:
    """Async API client for communicating with the AutomatedFanfic debug and control REST APIs."""

    def __init__(
        self,
        base_url: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = (
            client if client is not None else httpx.AsyncClient(base_url=self._base_url)
        )

    @property
    def base_url(self) -> str:
        """Base URL of the AutomatedFanfic web service."""
        return self._base_url

    @property
    def client(self) -> httpx.AsyncClient:
        """Underlying httpx AsyncClient instance."""
        return self._client

    @classmethod
    def from_url(
        cls, base_url: str = "http://localhost:8080"
    ) -> "AutomatedFanficClient":
        """Instantiate client pointing to external AutomatedFanfic HTTP/HTTPS instance."""
        client = httpx.AsyncClient(base_url=base_url)
        return cls(base_url=base_url, client=client)

    @classmethod
    def from_app(
        cls, app: FastAPI, base_url: str = "http://test"
    ) -> "AutomatedFanficClient":
        """Instantiate client directly against FastAPI ASGI application."""
        transport = httpx.ASGITransport(app=app)
        client = httpx.AsyncClient(transport=transport, base_url=base_url)
        return cls(base_url=base_url, client=client)

    async def __aenter__(self) -> "AutomatedFanficClient":
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        await self._client.__aexit__(exc_type, exc_val, exc_tb)

    async def close(self) -> None:
        """Close underlying httpx client transport."""
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform request and handle connection errors defensively."""
        try:
            response = await self._client.request(
                method=method,
                url=path,
                params=params,
                json=json,
            )
            if response.status_code == 200:
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        return data
                    return {"result": data}
                except Exception as exc:
                    return {
                        "ok": False,
                        "status_code": response.status_code,
                        "error": f"Invalid JSON response: {exc}",
                    }
            try:
                error_data = response.json()
                if isinstance(error_data, dict):
                    return error_data
                return {
                    "ok": False,
                    "status_code": response.status_code,
                    "error": error_data,
                }
            except Exception:
                return {
                    "ok": False,
                    "status_code": response.status_code,
                    "error": response.text,
                }
        except (httpx.ConnectError, httpx.NetworkError):  # fmt: skip
            return {
                "ok": False,
                "error": f"AutomatedFanfic web server is not reachable at {self._base_url}. Ensure 'web.enabled = true'.",
            }
        except httpx.RequestError as exc:
            return {
                "ok": False,
                "error": f"Request to AutomatedFanfic web server failed: {exc}",
            }

    async def get_health(self) -> dict[str, Any]:
        """Check system health status."""
        return await self._request("GET", "/api/health")

    async def get_queues(self) -> dict[str, Any]:
        """Inspect active URL partitions (queued, processing, waiting)."""
        return await self._request("GET", "/api/debug/queues/inspect")

    async def get_coordinator(self) -> dict[str, Any]:
        """Query coordinator worker domain assignments and backlogs."""
        return await self._request("GET", "/api/debug/coordinator")

    async def get_logs(
        self,
        level: str = "ALL",
        component: str = "",
        search: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        """Query filtered logs from memory buffer."""
        params: dict[str, Any] = {"level": level, "limit": limit}
        if component:
            params["component"] = component
        if search:
            params["search"] = search
        return await self._request("GET", "/api/debug/logs", params=params)

    async def get_story_diagnostics(self, url: str) -> dict[str, Any]:
        """Fetch complete autopsy diagnostics for a story URL."""
        return await self._request(
            "GET", "/api/debug/story/diagnostics", params={"url": url}
        )

    async def get_calibre_book(self, query: str) -> dict[str, Any]:
        """Look up Calibre book metadata by ID, URL, or title."""
        return await self._request(
            "GET", "/api/debug/calibre/book", params={"query": query}
        )

    async def get_antibot(self) -> dict[str, Any]:
        """Test FlareSolverr and Anubis anti-bot solver readiness."""
        return await self._request("GET", "/api/debug/antibot")

    async def get_cookiejar(self, domain: str) -> dict[str, Any]:
        """Inspect cookies loaded for domain."""
        return await self._request("GET", f"/api/debug/cookiejar/{domain}")

    async def resolve_config(self, url: str) -> dict[str, Any]:
        """Resolve FanFicFare configuration directives for a URL."""
        return await self._request(
            "POST", "/api/debug/resolve-config", json={"url": url}
        )

    async def run_diagnostic(self, service: str) -> dict[str, Any]:
        """Run connectivity diagnostics for calibre, email, notifications, or fanficfare."""
        return await self._request("POST", f"/api/debug/diagnostics/{service}")

    async def dry_run(self, url: str) -> dict[str, Any]:
        """Run FanFicFare metadata extraction without downloading chapters."""
        return await self._request("POST", "/api/debug/dry-run", json={"url": url})

    async def simulate_email(self, subject: str, body: str) -> dict[str, Any]:
        """Simulate email parsing and URL extraction."""
        return await self._request(
            "POST",
            "/api/debug/simulate-email",
            json={"subject": subject, "body": body},
        )

    async def add_url(self, url: str, force: bool = False) -> dict[str, Any]:
        """Inject URL into ingress queue with optional force re-download."""
        return await self._request(
            "POST", "/api/controls/add-url", json={"url": url, "force": force}
        )

    async def cancel_url(self, url: str) -> dict[str, Any]:
        """Cancel queued or retrying download."""
        return await self._request("POST", "/api/controls/cancel", json={"url": url})

    async def retry_now(self, url: str) -> dict[str, Any]:
        """Trigger immediate retry for waiting URL."""
        return await self._request("POST", "/api/controls/retry-now", json={"url": url})

    async def get_system_status(self) -> dict[str, Any]:
        """Fetch combined system health, version information, and runtime process status."""
        health = await self._request("GET", "/api/health")
        version = await self._request("GET", "/api/version")
        status = await self._request("GET", "/api/status")
        return {
            "health": health,
            "version": version,
            "status": status,
        }

    async def get_story_history(self, url: str) -> dict[str, Any]:
        """Retrieve full persistent download and retry history for a specific story URL."""
        return await self._request("GET", "/api/history/story", params={"url": url})

    async def get_downloads(
        self,
        search: str = "",
        site: str = "",
        status: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Query persistent download events from history database."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        if site:
            params["site"] = site
        if status:
            params["status"] = status
        return await self._request("GET", "/api/history/downloads", params=params)

    async def get_retries(
        self,
        search: str = "",
        site: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Query retry events across stories from history database."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        if site:
            params["site"] = site
        return await self._request("GET", "/api/history/retries", params=params)

    async def get_email_history(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Query recent email check events from history database."""
        return await self._request(
            "GET", "/api/history/emails", params={"limit": limit, "offset": offset}
        )

    async def get_notification_history(
        self,
        search: str = "",
        site: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Query sent notification events from history database."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        if site:
            params["site"] = site
        return await self._request("GET", "/api/history/notifications", params=params)

    async def get_config(self, section: str = "") -> dict[str, Any]:
        """Fetch current application configuration with sensitive values masked."""
        data = await self._request("GET", "/api/config")
        if section and "config" in data and isinstance(data["config"], dict):
            cfg_section = data["config"].get(section)
            if cfg_section is not None:
                return {"section": section, "values": cfg_section}
        return data

    async def get_ini_file(self, ini_type: str = "personal") -> dict[str, Any]:
        """Fetch contents of personal.ini or defaults.ini."""
        return await self._request("GET", f"/api/config/ini/{ini_type}")

    async def trigger_email_check(self) -> dict[str, Any]:
        """Trigger an immediate IMAP email polling check."""
        return await self._request("POST", "/api/controls/check-emails")

    async def restart_daemon(self, name: str) -> dict[str, Any]:
        """Trigger restart of a daemon process or service."""
        return await self._request(
            "POST", "/api/controls/restart-daemon", json={"name": name}
        )

    async def retry_all_waiting(self) -> dict[str, Any]:
        """Requeue all downloads currently in waiting/backoff state."""
        return await self._request("POST", "/api/controls/retry-all")

    async def toggle_site(self, site: str) -> dict[str, Any]:
        """Toggle site between enabled and disabled."""
        return await self._request(
            "POST", "/api/controls/toggle-site", json={"site": site}
        )

    async def redownload_scratch(self, url: str) -> dict[str, Any]:
        """Redownload a story completely fresh from scratch."""
        return await self._request(
            "POST", "/api/controls/redownload-scratch", json={"url": url}
        )

    async def recover_flaresolverr(self, target_site: str = "") -> dict[str, Any]:
        """Recover from FlareSolverr tab crashes by destroying dead sessions."""
        payload = {"target_site": target_site} if target_site else {}
        return await self._request(
            "POST", "/api/debug/flaresolverr/recover", json=payload
        )
