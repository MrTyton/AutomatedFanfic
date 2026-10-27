"""FastMCP log querying and filtering tools."""

from typing import Any
from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def query_logs(
    level: str = "ALL",
    component: str = "",
    search: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Query filtered logs from the in-memory log buffer."""
    client = get_client()
    return await client.get_logs(
        level=level, component=component, search=search, limit=limit
    )


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register log inspection tools on the FastMCP server."""
    register_tool(server, client, query_logs)
