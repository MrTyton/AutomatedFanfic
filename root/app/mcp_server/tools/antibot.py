"""FastMCP anti-bot solver reachability and cookiejar inspection tools."""

from typing import Any
from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def test_antibot_status() -> dict[str, Any]:
    """Test FlareSolverr and Anubis anti-bot solver reachability and readiness."""
    client = get_client()
    return await client.get_antibot()


test_antibot_status.__test__ = False


async def inspect_cookiejar(domain: str) -> dict[str, Any]:
    """Inspect cookies currently loaded in cookiejar for a domain."""
    client = get_client()
    return await client.get_cookiejar(domain=domain)


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register anti-bot and cookiejar tools on the FastMCP server."""
    register_tool(server, client, test_antibot_status)
    register_tool(server, client, inspect_cookiejar)
