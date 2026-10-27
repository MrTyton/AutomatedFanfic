"""FastMCP queue controls and manual download trigger tools."""

from typing import Any
from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def inject_download(url: str, force: bool = False) -> dict[str, Any]:
    """Inject fanfiction URL into download queue with optional force download."""
    client = get_client()
    return await client.add_url(url=url, force=force)


async def cancel_download(url: str) -> dict[str, Any]:
    """Cancel a queued or retrying fanfiction download."""
    client = get_client()
    return await client.cancel_url(url=url)


async def retry_now(url: str) -> dict[str, Any]:
    """Trigger immediate retry for a waiting fanfiction download."""
    client = get_client()
    return await client.retry_now(url=url)


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register download control tools on the FastMCP server."""
    register_tool(server, client, inject_download)
    register_tool(server, client, cancel_download)
    register_tool(server, client, retry_now)
