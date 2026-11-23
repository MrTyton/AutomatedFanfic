"""FastMCP tools for adaptive Calibre library update poller inspection and sync."""

from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def get_poller_status(site: str = "") -> dict[str, object]:
    """Get adaptive library update poller status, daily budgets, tier counts, and queued checks."""
    client = get_client()
    return await client.get_poller_status(site=site)


async def trigger_library_sync() -> dict[str, object]:
    """Trigger an immediate Calibre library sync scan in the library update poller."""
    client = get_client()
    return await client.trigger_library_sync()


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register library update poller tools on the FastMCP server."""
    register_tool(server, client, get_poller_status)
    register_tool(server, client, trigger_library_sync)
