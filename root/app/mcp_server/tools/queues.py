"""FastMCP queue partitioning and inspection tools."""

from typing import Any
from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def inspect_queues() -> dict[str, Any]:
    """Inspect active URL partitions across queued, processing, and waiting states."""
    client = get_client()
    return await client.get_queues()


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register queue inspection tools on the FastMCP server."""
    register_tool(server, client, inspect_queues)
