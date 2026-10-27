"""FastMCP Calibre library inspection and connection test tools."""

from typing import Any
from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def inspect_calibre_book(query: str) -> dict[str, Any]:
    """Inspect Calibre library book metadata by book ID, URL, or title."""
    client = get_client()
    return await client.get_calibre_book(query=query)


async def test_calibre_connection() -> dict[str, Any]:
    """Test connectivity and version info for the configured Calibre library."""
    client = get_client()
    return await client.run_diagnostic("calibre")


test_calibre_connection.__test__ = False


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register Calibre tools on the FastMCP server."""
    register_tool(server, client, inspect_calibre_book)
    register_tool(server, client, test_calibre_connection)
