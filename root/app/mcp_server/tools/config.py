"""FastMCP configuration inspection and resolution tools."""

from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def resolve_config_for_url(url: str) -> dict[str, object]:
    """Resolve effective FanFicFare configuration sections and directives for a URL."""
    client = get_client()
    return await client.resolve_config(url=url)


async def get_app_config(section: str = "") -> dict[str, object]:
    """Inspect current application configuration with sensitive fields masked (e.g. email, calibre, retry)."""
    client = get_client()
    return await client.get_config(section=section)


async def get_ini_file(ini_type: str = "personal") -> dict[str, object]:
    """Fetch raw configuration of personal.ini or defaults.ini."""
    client = get_client()
    return await client.get_ini_file(ini_type=ini_type)


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register config tools on the FastMCP server."""
    register_tool(server, client, resolve_config_for_url)
    register_tool(server, client, get_app_config)
    register_tool(server, client, get_ini_file)
