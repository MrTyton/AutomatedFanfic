"""AutomatedFanfic FastMCP server package."""

from mcp_server.cli import main, run_cli
from mcp_server.client import AutomatedFanficClient
from mcp_server.server import FastMCP, create_mcp_server
from mcp_server.tools import register_all_tools

__all__ = [
    "AutomatedFanficClient",
    "FastMCP",
    "create_mcp_server",
    "main",
    "register_all_tools",
    "run_cli",
]
