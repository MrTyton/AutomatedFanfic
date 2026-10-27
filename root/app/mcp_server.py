"""Standalone CLI entrypoint for AutomatedFanfic FastMCP server."""

from mcp_server.cli import main, run_cli

__all__ = ["main", "run_cli"]

if __name__ == "__main__":
    main()
