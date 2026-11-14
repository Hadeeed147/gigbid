"""Helpers for in-memory MCP tests (no network)."""
from contextlib import asynccontextmanager

from mcp.shared.memory import create_connected_server_and_client_session

from mcp_servers import local_identity


@asynccontextmanager
async def session(fastmcp, user: str = "ai_ml", trace: str = "test-trace"):
    token = local_identity.set((user, trace))
    try:
        async with create_connected_server_and_client_session(fastmcp._mcp_server) as s:
            yield s
    finally:
        local_identity.reset(token)
