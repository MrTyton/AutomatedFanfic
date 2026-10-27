"""FastMCP modular debugging and control tools suite."""

from mcp.server.mcpserver import MCPServer
from mcp_server.base import set_client
from mcp_server.client import AutomatedFanficClient
from mcp_server.tools import (
    antibot,
    calibre,
    config,
    controls,
    diagnostics,
    logs,
    queues,
    story,
    system,
)

FastMCP = MCPServer


def register_all_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register all modular FastMCP tools with the server bound to the client."""
    set_client(client)
    system.register_tools(server, client)
    queues.register_tools(server, client)
    logs.register_tools(server, client)
    story.register_tools(server, client)
    calibre.register_tools(server, client)
    antibot.register_tools(server, client)
    config.register_tools(server, client)
    diagnostics.register_tools(server, client)
    controls.register_tools(server, client)


__all__ = ["register_all_tools"]
