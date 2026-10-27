"""FastMCP story diagnostics and autopsy tools."""

from typing import Any
from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def get_story_diagnostics(url: str) -> dict[str, Any]:
    """Fetch diagnostic autopsy report and history for a story URL."""
    client = get_client()
    return await client.get_story_diagnostics(url=url)


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register story diagnostic tools on the FastMCP server."""
    register_tool(server, client, get_story_diagnostics)
