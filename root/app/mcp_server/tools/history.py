"""FastMCP persistent SQLite history inspection tools."""

from mcp.server.mcpserver import MCPServer
from mcp_server.base import get_client, register_tool
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer


async def get_story_history(url: str) -> dict[str, object]:
    """Retrieve full persistent download and retry lifecycle history for a story URL."""
    client = get_client()
    return await client.get_story_history(url=url)


async def query_download_history(
    search: str = "",
    site: str = "",
    status: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    """Query persistent download events from SQLite history database."""
    client = get_client()
    return await client.get_downloads(
        search=search, site=site, status=status, limit=limit, offset=offset
    )


async def query_retry_history(
    search: str = "",
    site: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    """Query persistent retry failure events from SQLite history database."""
    client = get_client()
    return await client.get_retries(
        search=search, site=site, limit=limit, offset=offset
    )


async def query_email_history(
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    """Query recent IMAP email check events and detected story URLs from history database."""
    client = get_client()
    return await client.get_email_history(limit=limit, offset=offset)


async def query_notification_history(
    search: str = "",
    site: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    """Query sent notification events from SQLite history database."""
    client = get_client()
    return await client.get_notification_history(
        search=search, site=site, limit=limit, offset=offset
    )


def register_tools(server: FastMCP, client: AutomatedFanficClient) -> None:
    """Register persistent history inspection tools on the FastMCP server."""
    register_tool(server, client, get_story_history)
    register_tool(server, client, query_download_history)
    register_tool(server, client, query_retry_history)
    register_tool(server, client, query_email_history)
    register_tool(server, client, query_notification_history)
