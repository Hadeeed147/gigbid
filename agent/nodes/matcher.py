"""Fit Matcher: map every requirement to portfolio evidence (via the Portfolio
MCP server) and produce a fit score with reasons.

Runs in parallel with the Job Analyst, so it decomposes the post itself
(deterministic splitter) instead of waiting for the JobSpec."""
from __future__ import annotations

import json

from agent.handoffs import FitReport
from agent.mcp_client import get_hub
from agent.nodes._runtime import node, strip_injection
from common.llm import chat
from common.prompts import load_prompt
from rag.variants.base import rule_requirements

SCORE = {"strong": 1.0, "partial": 0.5, "none": 0.0}


@node("matcher")
async def matcher(state: dict) -> dict:
    job = state["job"]
    text = job.get("title", "") + "\n" + strip_injection(job.get("description", ""))
    reqs = rule_requirements(text)[:6] or [job.get("title", "")]
    hub = await get_hub()
    evidence: dict[str, list[dict]] = {}
    support: dict[str, str] = {}
    for r in reqs:
        res = await hub.call("matcher", "search_evidence", {"requirement": r[:400], "k": 3})
        evidence[r] = res.get("items", [])
        if res.get("support"):
            support[r] = res["support"]
    ev_txt = "\n\n".join(
        f"REQUIREMENT: {r}\n" + ("\n".join(f"  [{e['item_id']}] ({e['type']}, score {e['score']}) {e['text'][:300]}"
                                           for e in items) or "  (no evidence found)")
        for r, items in evidence.items())
    rep = chat("matcher", [{"role": "system", "content": load_prompt("matcher")},
                           {"role": "user", "content": ev_txt + f"\n\nRetriever support grades: {json.dumps(support)}"}],
               FitReport)
    # keep only evidence ids that really were retrieved (no hallucinated ids)
    valid = {e["item_id"] for items in evidence.values() for e in items}
    for m in rep.matrix:
        m.evidence_ids = [i for i in m.evidence_ids if i in valid]
        if m.strength != "none" and not m.evidence_ids:
            m.strength = "none"
    if rep.matrix:
        rep.fit_score = round(sum(SCORE[m.strength] for m in rep.matrix) / len(rep.matrix), 3)
    return {"fit": rep.model_dump(), "evidence": evidence}
