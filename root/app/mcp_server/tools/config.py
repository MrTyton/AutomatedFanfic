"""FastMCP configuration resolution tools."""

from typing import Any
from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def resolve_config_for_url(url: str) -> dict[str, Any]:
    """Resolve effective FanFicFare configuration sections and directives for a URL."""
    client = get_client()
    return await client.resolve_config(url=url)


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register config resolution tools on the FastMCP server."""
    register_tool(server, client, resolve_config_for_url)
