"""FastMCP server initialization and client attachment."""

from mcp.server.mcpserver import MCPServer
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


def create_mcp_server(client: AutomatedFanficClient) -> FastMCP:
    """Create and configure a FastMCP server instance attached to AutomatedFanficClient."""
    server = FastMCP("AutomatedFanfic")
    server.client = client
    return server
