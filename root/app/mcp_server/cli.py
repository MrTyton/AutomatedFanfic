"""Standalone stdio CLI runner for AutomatedFanfic FastMCP server."""

import asyncio
import inspect
import os
import sys
import httpx

from mcp_server.client import AutomatedFanficClient
from mcp_server.server import create_mcp_server


def run_cli(check_connection: bool = True) -> int:
    """Run FastMCP server over stdio transport.

    Args:
        check_connection: Whether to perform preflight connectivity check
            against AutomatedFanfic web API before starting stdio loop.

    Returns:
        Process exit code (0 for success, 1 for connection or runtime error).
    """
    api_url = os.environ.get("AUTOMATEDFANFIC_API_URL", "http://localhost:8080")
    client = AutomatedFanficClient.from_url(api_url)
    server = create_mcp_server(client)

    if check_connection:
        try:
            health_call = client.get_health()
            res = (
                asyncio.run(health_call)
                if inspect.iscoroutine(health_call)
                else health_call
            )
            if isinstance(res, dict) and not res.get("ok", True):
                sys.stderr.write(
                    f"Error: Unable to connect to AutomatedFanfic API at {api_url}: {res.get('error')}\n"
                    "Ensure the AutomatedFanfic service is running and 'web.enabled = true' in config.toml.\n"
                )
                return 1
        except (httpx.HTTPError, ConnectionError, OSError) as exc:
            sys.stderr.write(
                f"Error: Unable to connect to AutomatedFanfic API at {api_url}: {exc}\n"
                "Ensure the AutomatedFanfic service is running and 'web.enabled = true' in config.toml.\n"
            )
            return 1

    try:
        server.run(transport="stdio")
        return 0
    except (httpx.HTTPError, ConnectionError, OSError) as exc:
        sys.stderr.write(
            f"Error: Connection error with AutomatedFanfic API at {api_url}: {exc}\n"
            "Ensure the AutomatedFanfic service is running and 'web.enabled = true' in config.toml.\n"
        )
        return 1


def main() -> None:
    """Entrypoint function for CLI and module execution."""
    exit_code = run_cli(check_connection=True)
    sys.exit(exit_code)
