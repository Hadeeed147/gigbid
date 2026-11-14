"""Portfolio MCP server (read-only): evidence search over a freelancer's portfolio.

Usable on its own from Claude Desktop / Cursor:
    uv run python -m mcp_servers.portfolio.server --transport stdio --portfolio-dir ./my_portfolio
Inside GigBid it runs over Streamable HTTP and serves every tenant; the tenant
comes from the X-GigBid-User header set by the agent, never from a tool argument.
"""
from __future__ import annotations

import argparse
import os

from mcp.server.fastmcp import FastMCP

from mcp_servers.common import auth_kwargs
from mcp_servers.portfolio import prompts, resources, tools

PORT = 8201
mcp = FastMCP(
    "gigbid-portfolio",
    instructions=("Read-only access to a freelancer's portfolio: CV, case studies, repos, client reviews and past "
                  "proposals with outcomes. Use search_evidence to find proof for a job requirement; every result "
                  "has an item id you can cite."),
    port=PORT, host="0.0.0.0", stateless_http=True, json_response=True, **auth_kwargs(PORT))

tools.register(mcp)
resources.register(mcp)
prompts.register(mcp)


def main() -> None:
    ap = argparse.ArgumentParser(description="GigBid Portfolio MCP server")
    ap.add_argument("--transport", default="streamable-http", choices=["streamable-http", "stdio"])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--portfolio-dir", help="Folder with cv.pdf|cv.md, case_studies/, repos/, reviews.json, "
                                            "proposals.json (standalone mode)")
    ap.add_argument("--tenant", default="me", help="Tenant name for standalone mode")
    a = ap.parse_args()
    if a.portfolio_dir:
        os.environ["PORTFOLIO_STANDALONE_DIR"] = os.path.abspath(a.portfolio_dir)
        os.environ["PORTFOLIO_STANDALONE_TENANT"] = a.tenant
    mcp.settings.port = a.port
    mcp.run(transport=a.transport)


if __name__ == "__main__":
    main()
