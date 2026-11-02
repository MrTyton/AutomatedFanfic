"""FastMCP anti-bot solver reachability, cookiejar inspection, and session recovery tools."""

from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def test_antibot_status() -> dict[str, object]:
    """Test FlareSolverr and Anubis anti-bot solver reachability and readiness."""
    client = get_client()
    return await client.get_antibot()


setattr(test_antibot_status, "__test__", False)


async def inspect_cookiejar(domain: str) -> dict[str, object]:
    """Inspect cookies currently loaded in cookiejar for a domain."""
    client = get_client()
    return await client.get_cookiejar(domain=domain)


async def recover_flaresolverr(target_site: str = "") -> dict[str, object]:
    """Recover from FlareSolverr Chromium tab crashes by destroying dead sessions."""
    client = get_client()
    return await client.recover_flaresolverr(target_site=target_site)


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register anti-bot and cookiejar tools on the FastMCP server."""
    register_tool(server, client, test_antibot_status)
    register_tool(server, client, inspect_cookiejar)
    register_tool(server, client, recover_flaresolverr)
