"""Portfolio tools: search_evidence, get_case_study, list_skills (all read-only)."""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from data.generators.skills import SKILLS
from mcp_servers.common import AuditLog, caller
from rag.retriever import get_store, get_variant
from rag.variants.base import RetrievalQuery

RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_audit = AuditLog("portfolio")

EvidenceType = Literal["case_study", "readme", "code", "review", "cv", "proposal"]


def tenant_of(ctx: Context | None) -> tuple[str, str]:
    """Standalone mode serves one folder; inside GigBid the tenant is the caller's user id/persona."""
    standalone = os.environ.get("PORTFOLIO_STANDALONE_DIR")
    if standalone:
        # The folder name is the tenant; its parent is where the store looks for tenants.
        import rag.retriever as r
        r.PERSONAS_DIR = Path(standalone).parent
        return Path(standalone).name, ""
    _, trace, tenant = caller(ctx)
    return tenant, trace


class SearchFilters(BaseModel):
    types: list[EvidenceType] = Field(default_factory=list, description="Restrict to these evidence types")
    project_id: str | None = None
    since: str | None = Field(default=None, description="Only items dated on/after this ISO date")
    outcome: Literal["won", "replied", "ignored"] | None = Field(default=None, description="Proposals only")


class EvidenceItem(BaseModel):
    item_id: str
    type: str
    title: str
    project_id: str | None = None
    source: str
    date: str = ""
    outcome: str | None = None
    client_industry: str = ""
    score: float
    text: str


class EvidenceList(BaseModel):
    requirement: str
    variant: str
    support: str | None = Field(default=None, description="supported | weak | none (corrective variant)")
    items: list[EvidenceItem]


class CaseStudy(BaseModel):
    item_id: str
    title: str
    project_id: str | None = None
    text: str
    related_items: list[str]


class SkillCount(BaseModel):
    skill: str
    name: str
    evidence_items: int


class SkillList(BaseModel):
    skills: list[SkillCount]


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=RO, title="Search portfolio evidence")
    async def search_evidence(
        requirement: Annotated[str, Field(min_length=2, max_length=500,
                                          description="One job requirement, e.g. 'nightly report queue with retries'")],
        k: Annotated[int, Field(ge=1, le=20)] = 5,
        filters: SearchFilters | None = None,
        ctx: Context | None = None,
    ) -> EvidenceList:
        """Find portfolio items that prove a requirement. Returns items with type, source, date and outcome."""
        tenant, trace = tenant_of(ctx)
        store = get_store()
        if not store.items(tenant):
            raise ToolError(f"no portfolio found for tenant '{tenant}'")
        f = filters or SearchFilters()
        if f.types and set(f.types) == {"proposal"}:
            # past proposals are phrasing exemplars, never evidence: plain similarity + outcome filter
            hits = store.structured(tenant).dense(requirement, k * 6, types={"proposal"})
            if f.outcome:
                hits = [h for h in hits if h.chunk.outcome == f.outcome]
            items = [EvidenceItem(**{k2: v for k2, v in h.to_evidence().items() if k2 in EvidenceItem.model_fields})
                     for h in hits[:k]]
            return EvidenceList(requirement=requirement, variant="proposal_similarity", items=items)
        variant = get_variant()
        res = variant.retrieve(RetrievalQuery(tenant=tenant, job_text=requirement, requirements=[requirement]),
                               k * 3 if (f.types or f.project_id or f.since or f.outcome) else k)
        hits = res.hits
        if f.types:
            hits = [h for h in hits if h.chunk.type in f.types]
        if f.project_id:
            hits = [h for h in hits if h.chunk.project_id == f.project_id]
        if f.since:
            hits = [h for h in hits if (h.chunk.date or "") >= f.since]
        if f.outcome:
            hits = [h for h in hits if h.chunk.outcome == f.outcome]
        items = [EvidenceItem(**{k2: v for k2, v in h.to_evidence().items() if k2 in EvidenceItem.model_fields})
                 for h in hits[:k]]
        out = EvidenceList(requirement=requirement, variant=variant.name,
                           support=res.support.get(requirement) if res.support else None, items=items)
        _audit.write(user=tenant, tool="search_evidence", args={"requirement": requirement, "k": k},
                     result={"items": [i.item_id for i in items]}, trace_id=trace)
        return out

    @mcp.tool(annotations=RO, title="Get case study")
    async def get_case_study(item_id: Annotated[str, Field(min_length=3, max_length=120)],
                             ctx: Context | None = None) -> CaseStudy:
        """Full text of one portfolio item (case study, README, code file, review) plus related item ids."""
        tenant, _ = tenant_of(ctx)
        it = get_store().get_item(tenant, item_id)
        if not it:
            raise ToolError(f"item {item_id} not found")
        related = [x.item_id for x in get_store().items(tenant)
                   if it.project_id and x.project_id == it.project_id and x.item_id != item_id]
        return CaseStudy(item_id=it.item_id, title=it.title, project_id=it.project_id, text=it.text,
                         related_items=related)

    @mcp.tool(annotations=RO, title="List skills")
    async def list_skills(ctx: Context | None = None) -> SkillList:
        """Skills evidenced anywhere in the portfolio, with how many items mention each."""
        tenant, _ = tenant_of(ctx)
        counts: Counter = Counter()
        for c in get_store().structured(tenant).chunks:
            for s in set(c.skills):
                counts[s] += 1
        return SkillList(skills=[SkillCount(skill=s, name=SKILLS.get(s, {"names": [s]})["names"][0], evidence_items=n)
                                 for s, n in counts.most_common()])
