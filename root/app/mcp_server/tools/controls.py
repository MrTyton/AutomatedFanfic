"""FastMCP queue controls and manual download trigger tools."""

from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def inject_download(url: str, force: bool = False) -> dict[str, object]:
    """Inject fanfiction URL into download queue with optional force download."""
    client = get_client()
    return await client.add_url(url=url, force=force)


async def cancel_download(url: str) -> dict[str, object]:
    """Cancel a queued or retrying fanfiction download."""
    client = get_client()
    return await client.cancel_url(url=url)


async def retry_now(url: str) -> dict[str, object]:
    """Trigger immediate retry for a waiting fanfiction download."""
    client = get_client()
    return await client.retry_now(url=url)


async def trigger_email_check() -> dict[str, object]:
    """Trigger an immediate IMAP email polling check by waking EmailWatcher."""
    client = get_client()
    return await client.trigger_email_check()


async def restart_daemon(name: str) -> dict[str, object]:
    """Trigger restart of a daemon process or service (e.g. EmailWatcher, Coordinator, WebServer)."""
    client = get_client()
    return await client.restart_daemon(name=name)


async def retry_all_waiting() -> dict[str, object]:
    """Requeue all downloads currently in waiting/backoff state for immediate retry."""
    client = get_client()
    return await client.retry_all_waiting()


async def toggle_site(site: str) -> dict[str, object]:
    """Toggle site domain between enabled and disabled in email watcher configuration."""
    client = get_client()
    return await client.toggle_site(site=site)


async def redownload_from_scratch(url: str) -> dict[str, object]:
    """Redownload a story completely from scratch, removing existing EPUB and cached state."""
    client = get_client()
    return await client.redownload_scratch(url=url)


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register download control tools on the FastMCP server."""
    register_tool(server, client, inject_download)
    register_tool(server, client, cancel_download)
    register_tool(server, client, retry_now)
    register_tool(server, client, trigger_email_check)
    register_tool(server, client, restart_daemon)
    register_tool(server, client, retry_all_waiting)
    register_tool(server, client, toggle_site)
    register_tool(server, client, redownload_from_scratch)
