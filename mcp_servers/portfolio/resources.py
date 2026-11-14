"""Resource templates so an MCP host can load full portfolio items."""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from rag.retriever import get_store


def register(mcp: FastMCP) -> None:
    def _tenant() -> str:
        from mcp_servers.portfolio.tools import tenant_of
        return tenant_of(None)[0]

    @mcp.resource("portfolio://case/{item_id}", name="case_study", mime_type="text/markdown",
                  description="A case study (or README / code / review) by item id, e.g. ai_ml:cs:03")
    def case(item_id: str) -> str:
        it = get_store().get_item(_tenant(), item_id) or get_store().get_item(item_id.split(":")[0], item_id)
        return it.text if it else f"not found: {item_id}"

    @mcp.resource("portfolio://proposal/{item_id}", name="past_proposal", mime_type="application/json",
                  description="A past proposal with its outcome (won | replied | ignored)")
    def proposal(item_id: str) -> str:
        tenant = item_id.split(":")[0]
        it = get_store().get_item(tenant, item_id) or get_store().get_item(_tenant(), item_id)
        if not it:
            return json.dumps({"error": f"not found: {item_id}"})
        return json.dumps({"id": it.item_id, "job_title": it.title, "outcome": it.outcome, "text": it.text,
                           **it.extra})

    @mcp.resource("portfolio://cv/{tenant}", name="cv", mime_type="text/plain", description="The freelancer's CV")
    def cv(tenant: str) -> str:
        it = get_store().get_item(tenant, f"{tenant}:cv")
        return it.text if it else "no CV"
