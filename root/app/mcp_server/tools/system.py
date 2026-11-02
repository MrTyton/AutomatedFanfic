"""FastMCP system health and coordinator inspection tools."""

from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def get_system_overview() -> dict[str, object]:
    """Fetch system health, component versions (Calibre, FanFicFare, OS), and runtime process status."""
    client = get_client()
    return await client.get_system_status()


async def inspect_coordinator_locks() -> dict[str, object]:
    """Inspect coordinator worker domain locks, active assignments, and backlogs."""
    client = get_client()
    return await client.get_coordinator()


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register system and coordinator inspection tools on the FastMCP server."""
    register_tool(server, client, get_system_overview)
    register_tool(server, client, inspect_coordinator_locks)
