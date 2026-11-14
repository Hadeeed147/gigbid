"""Proposal studio + approvals. The pending approval is read from the graph
checkpoint (Postgres), so a page refresh or API restart never loses it; approving
enqueues a resume of that exact interrupted thread in the worker."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent.runtime import pending_interrupt
from apps.api import db
from apps.api.auth.security import current_user
from apps.api.deps import PRIORITY, arq, graphs, trace_id
from apps.api.schemas.models import ApprovalIn, ParagraphIn, ParagraphOut, QueuedOut, StudioOut
from common.llm import chat
from common.prompts import load_prompt

router = APIRouter(tags=["proposals", "approvals"])


def _thread(user_id: str, job_id: str) -> str:
    r = db.one("SELECT thread_id FROM inbox WHERE user_id=%s AND job_id=%s", (user_id, job_id))
    if not r:
        raise HTTPException(404, "job not in your inbox")
    return r["thread_id"]


@router.get("/proposals/{job_id}", response_model=StudioOut)
async def studio(job_id: str, user: dict = Depends(current_user), g=Depends(graphs)) -> StudioOut:
    tid = _thread(user["id"], job_id)
    payload = await pending_interrupt(g[0], tid)
    snap = await g[0].aget_state({"configurable": {"thread_id": tid}})
    v = snap.values or {}
    if payload is None and v.get("draft"):   # finished thread: show what was sent / rejected
        payload = {"type": "proposal_approval", "draft": v.get("draft"), "evidence": v.get("evidence", {}),
                   "fit": v.get("fit"), "risk": v.get("risk"), "price": v.get("price"),
                   "verification": v.get("verification"), "critiques": v.get("critiques", []),
                   "compliance": v.get("compliance"), "dry_run_preview": v.get("preview"),
                   "job": {k: (v.get("job") or {}).get(k) for k in ("id", "title", "category", "budget", "connects_cost")}}
    return StudioOut(job_id=job_id, thread_id=tid, status=v.get("status"), pending=bool(snap.next and payload),
                     payload=payload, submission=v.get("submission"), approvals=v.get("approvals", []),
                     attention_reason=v.get("attention_reason"))


@router.post("/approvals/{job_id}", response_model=QueuedOut, status_code=202)
async def decide(job_id: str, body: ApprovalIn, user: dict = Depends(current_user), g=Depends(graphs),
                 pool=Depends(arq), tid: str = Depends(trace_id)) -> QueuedOut:
    thread = _thread(user["id"], job_id)
    if body.action == "reject" and not (body.reason or "").strip():
        raise HTTPException(422, "a reason is required to reject")
    if body.action == "edit" and not (body.text or "").strip():
        raise HTTPException(422, "edited text is required")
    if await pending_interrupt(g[0], thread) is None:
        raise HTTPException(409, "nothing is waiting for approval on this job")
    j = await pool.enqueue_job("resume_bid", user["id"], thread, body.model_dump(exclude_none=True), tid,
                               **PRIORITY, _job_id=f"resume:{thread}:{body.action}:{hash(body.text or '') & 0xffff}")
    db.q("UPDATE inbox SET status='resuming', updated_at=now() WHERE user_id=%s AND job_id=%s", (user["id"], job_id))
    return QueuedOut(queued=j is not None, job="resume_bid", trace_id=tid)


@router.post("/proposals/{job_id}/paragraph", response_model=ParagraphOut)
def regenerate_paragraph(job_id: str, body: ParagraphIn, user: dict = Depends(current_user)) -> ParagraphOut:
    """Rewrite one paragraph (short interactive call). The result goes back through
    Compliance when the user submits the edit."""
    _thread(user["id"], job_id)
    out = chat("writer", [{"role": "system", "content": load_prompt("writer_paragraph")},
                          {"role": "user", "content": f"Instruction: {body.instruction}\n\nParagraph:\n{body.paragraph}"}])
    return ParagraphOut(paragraph=str(out).strip())


@router.get("/approvals/pending")
def pending(user: dict = Depends(current_user)) -> dict:
    rows = db.q("SELECT job_id, title FROM inbox WHERE user_id=%s AND status='awaiting_approval' ORDER BY updated_at DESC",
                (user["id"],))
    convs = db.q("SELECT thread_id, title FROM conversations WHERE user_id=%s AND status='awaiting_approval'", (user["id"],))
    return {"proposals": rows, "messages": convs}
