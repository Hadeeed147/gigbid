"""Claim verification node (B3): unsupported claims are removed or rewritten
before the Critic sees the draft; before/after counts are kept for reporting."""
from __future__ import annotations

from agent.nodes._runtime import node
from rag.verify import verify


@node("verifier")
async def verifier(state: dict) -> dict:
    draft = dict(state["draft"])
    given = [e for items in (state.get("evidence") or {}).values() for e in items]
    tenant = state.get("tenant", "")
    rep = verify(draft["cover_letter"], tenant, given)
    answers, ans_unsupported, ans_claims = [], 0, 0
    for a in draft.get("screening_answers", []):
        r = verify(a, tenant, given)
        answers.append(r.revised_text or a)
        ans_unsupported += r.unsupported_before
        ans_claims += r.claims_total
    after = verify(rep.revised_text, tenant, given, grader="ce") if rep.unsupported_before else rep
    draft["cover_letter"] = rep.revised_text
    draft["screening_answers"] = answers
    report = {"claims": [c.model_dump() for c in rep.claims], "claims_total": rep.claims_total + ans_claims,
              "unsupported_before": rep.unsupported_before + ans_unsupported,
              "unsupported_after": after.unsupported_before if after is not rep else 0}
    return {"draft": draft, "verification": report, "status": "critiquing"}
