"""Base client context and tool registration helpers for FastMCP tools."""

from contextvars import ContextVar
import functools
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar
from mcp.server.mcpserver import MCPServer
from mcp_server.client import AutomatedFanficClient

FastMCP = MCPServer

_P = ParamSpec("_P")
_R = TypeVar("_R")

_current_client: ContextVar[AutomatedFanficClient | None] = ContextVar(
    "current_client", default=None
)
_default_client: AutomatedFanficClient | None = None


def set_client(client: AutomatedFanficClient | None) -> None:
    """Set or clear the active default AutomatedFanficClient."""
    global _default_client
    _default_client = client
    _current_client.set(client)


def get_client() -> AutomatedFanficClient:
    """Retrieve active AutomatedFanficClient for tool execution."""
    client = _current_client.get()
    if client is not None:
        return client
    if _default_client is not None:
        return _default_client
    raise RuntimeError("No AutomatedFanficClient configured for MCP tools.")


def register_tool(
    server: FastMCP,
    client: AutomatedFanficClient,
    fn: Callable[_P, Coroutine[Any, Any, _R]],
) -> None:
    """Register tool on FastMCP server bound to the given client instance."""

    @functools.wraps(fn)
    async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        token = _current_client.set(client)
        try:
            return await fn(*args, **kwargs)
        finally:
            _current_client.reset(token)

    server.add_tool(wrapped)
