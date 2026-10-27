"""FastMCP diagnostics, email simulation, and dry run tools."""

from typing import Any
from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def test_email_connection() -> dict[str, Any]:
    """Test IMAP email server connectivity, authentication, and unread count."""
    client = get_client()
    return await client.run_diagnostic("email")


test_email_connection.__test__ = False


async def test_notification(
    title: str = "Test",
    body: str = "Test Notification",
) -> dict[str, Any]:
    """Send a test notification via configured Apprise notification endpoints."""
    client = get_client()
    return await client.run_diagnostic("notifications")


test_notification.__test__ = False


async def simulate_email_parse(subject: str, body: str) -> dict[str, Any]:
    """Simulate email parsing to extract fanfiction URLs from subject and body."""
    client = get_client()
    return await client.simulate_email(subject=subject, body=body)


async def dry_run_fanfic_url(url: str) -> dict[str, Any]:
    """Run FanFicFare metadata extraction for a URL without downloading chapters."""
    client = get_client()
    return await client.dry_run(url=url)


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register diagnostic tools on the FastMCP server."""
    register_tool(server, client, test_email_connection)
    register_tool(server, client, test_notification)
    register_tool(server, client, simulate_email_parse)
    register_tool(server, client, dry_run_fanfic_url)
