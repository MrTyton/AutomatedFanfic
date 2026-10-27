"""FastMCP server initialization and client attachment."""

from mcp.server.mcpserver import MCPServer
from mcp_server.client import AutomatedFanficClient
from mcp_server.tools import register_all_tools

FastMCP = MCPServer


def create_mcp_server(client: AutomatedFanficClient) -> FastMCP:
    """Create and configure a FastMCP server instance attached to AutomatedFanficClient."""
    server = FastMCP("AutomatedFanfic")
    server.client = client
    register_all_tools(server, client)
    return server
