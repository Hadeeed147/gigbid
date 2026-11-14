"""Human-in-the-loop (C5): dry_run preview, interrupt() for approval, submit exactly once.

Nothing is sent and no Connects are spent unless the human approved in the UI.
Idempotency keys are derived from the thread id (and the approved text), so a
crash between approval and submission can never double-submit (C6)."""
from __future__ import annotations

import difflib
import hashlib

from langgraph.types import interrupt

from agent.handoffs import ApprovalDecision
from agent.mcp_client import get_hub
from agent.memory.store import record_edit
from agent.nodes._runtime import node
from agent.nodes.writer import strip_citations


def _key(thread_id: str, kind: str, text: str = "") -> str:
    return f"{thread_id}:{kind}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"


@node("preview")
async def preview(state: dict) -> dict:
    draft, price = state["draft"], state.get("price", {})
    hub = await get_hub()
    res = await hub.call("approval", "create_proposal_draft", {
        "job_id": state["job"]["id"], "cover_letter": strip_citations(draft["cover_letter"]),
        "bid_amount": price.get("amount") or 1, "screening_answers": [strip_citations(a) for a in draft.get("screening_answers", [])],
        "idempotency_key": _key(state["thread_id"], "preview"), "dry_run": True})
    return {"preview": res.get("result", res), "status": "awaiting_approval"}


@node("approval", allow_terminal=False)
async def approval(state: dict) -> dict:
    """Interrupts the graph. Code before interrupt() re-runs on resume, so it is side-effect free."""
    payload = {
        "type": "proposal_approval",
        "job": {k: state["job"].get(k) for k in ("id", "title", "category", "budget", "connects_cost",
                                                   "screening_questions")},
        "draft": state["draft"],
        "evidence": state.get("evidence", {}),
        "fit": state.get("fit", {}),
        "risk": state.get("risk", {}),
        "price": state.get("price", {}),
        "verification": state.get("verification", {}),
        "critiques": state.get("critiques", []),
        "compliance": state.get("compliance", {}),
        "dry_run_preview": state.get("preview", {}),
    }
    decision = ApprovalDecision(**interrupt(payload))
    rec = decision.model_dump()
    if decision.action == "reject":
        return {"approvals": [rec], "status": "rejected",
                "attention_reason": f"rejected: {decision.reason or 'no reason given'}"}
    if decision.action == "edit":
        draft = dict(state["draft"])
        before = draft["cover_letter"]
        after = decision.text or before
        rec["diff"] = "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0))
        record_edit(state.get("user_id", ""), before, after)   # candidate only; promotion rule decides
        draft["cover_letter"] = after
        if decision.screening_answers is not None:
            draft["screening_answers"] = decision.screening_answers
        price = dict(state.get("price", {}))
        if decision.bid_amount:
            price["amount"] = decision.bid_amount
        return {"approvals": [rec], "draft": draft, "price": price, "status": "recheck"}
    price = dict(state.get("price", {}))
    if decision.bid_amount:
        price["amount"] = decision.bid_amount
    return {"approvals": [rec], "price": price, "status": "approved"}


@node("submit")
async def submit(state: dict) -> dict:
    draft, price = state["draft"], state.get("price", {})
    text = strip_citations(draft["cover_letter"])
    answers = [strip_citations(a) for a in draft.get("screening_answers", [])]
    hub = await get_hub()
    created = await hub.call("submit", "create_proposal_draft", {
        "job_id": state["job"]["id"], "cover_letter": text, "bid_amount": price.get("amount") or 1,
        "screening_answers": answers, "idempotency_key": _key(state["thread_id"], "draft", text)})
    pid = created["result"]["id"]
    sub = await hub.call("submit", "submit_proposal", {"proposal_id": pid,
                                                       "idempotency_key": _key(state["thread_id"], "submit")})
    return {"submission": {"proposal_id": pid, **sub["result"], "replayed": sub.get("replayed", False)},
            "status": "submitted"}
