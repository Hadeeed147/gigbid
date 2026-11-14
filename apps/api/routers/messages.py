"""Client conversations: threads, suggested replies with interview slots, approve before sending."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent.mcp_client import get_hub, run_identity
from agent.runtime import pending_interrupt
from apps.api import db
from apps.api.auth.security import current_user
from apps.api.deps import PRIORITY, arq, graphs, iso, trace_id
from apps.api.schemas.models import ApprovalIn, ConversationOut, PipelineCard, QueuedOut, ThreadOut

router = APIRouter(tags=["messages", "pipeline"])


def _conv(r: dict) -> ConversationOut:
    return ConversationOut(**{**{k: r.get(k) for k in ConversationOut.model_fields}, "updated_at": iso(r.get("updated_at"))})


@router.get("/messages", response_model=list[ConversationOut])
def conversations(user: dict = Depends(current_user)) -> list[ConversationOut]:
    return [_conv(r) for r in db.q("SELECT * FROM conversations WHERE user_id=%s ORDER BY "
                                   "(status='awaiting_approval') DESC, updated_at DESC", (user["id"],))]


@router.get("/messages/{thread_id}", response_model=ThreadOut)
async def thread(thread_id: str, user: dict = Depends(current_user), g=Depends(graphs)) -> ThreadOut:
    r = db.one("SELECT * FROM conversations WHERE user_id=%s AND thread_id=%s", (user["id"], thread_id))
    if not r:
        raise HTTPException(404, "conversation not found")
    gt = (db.get_status(f"conv_thread:{user['id']}:{thread_id}") or {}).get("graph_thread", f"conv:{user['id']}:{thread_id}")
    pending = await pending_interrupt(g[1], gt)
    hub = await get_hub()
    tok = run_identity.set((user["id"], "", user["tenant"]))
    try:
        msgs = (await hub.call("liaison", "list_messages", {"thread_id": thread_id}))["items"]
    except Exception:  # noqa: BLE001 - degraded mode: show what we have
        msgs = []
    finally:
        run_identity.reset(tok)
    return ThreadOut(conversation=_conv(r), messages=msgs, pending=pending)


@router.post("/messages/{thread_id}/approve", response_model=QueuedOut, status_code=202)
async def approve(thread_id: str, body: ApprovalIn, user: dict = Depends(current_user), pool=Depends(arq),
                  tid: str = Depends(trace_id)) -> QueuedOut:
    if body.action == "reject" and not body.reason:
        raise HTTPException(422, "a reason is required to reject")
    j = await pool.enqueue_job("resume_conversation", user["id"], thread_id, body.model_dump(exclude_none=True), tid,
                               **PRIORITY, _job_id=f"resume-conv:{thread_id}:{body.action}:{hash(body.text or '') & 0xffff}")
    db.q("UPDATE conversations SET status='resuming' WHERE user_id=%s AND thread_id=%s", (user["id"], thread_id))
    return QueuedOut(queued=j is not None, job="resume_conversation", trace_id=tid)


@router.get("/pipeline", response_model=list[PipelineCard])
def pipeline(user: dict = Depends(current_user)) -> list[PipelineCard]:
    rows = db.q("SELECT * FROM pipeline WHERE user_id=%s ORDER BY updated_at DESC", (user["id"],))
    drafted = db.q("SELECT job_id, title, category, updated_at FROM inbox WHERE user_id=%s AND "
                   "status IN ('awaiting_approval','resuming')", (user["id"],))
    cards = [PipelineCard(proposal_id=f"draft:{d['job_id']}", job_id=d["job_id"], title=d["title"],
                          category=d["category"], stage="drafted", updated_at=iso(d["updated_at"])) for d in drafted]
    return cards + [PipelineCard(**{**{k: r.get(k) for k in PipelineCard.model_fields}, "updated_at": iso(r["updated_at"])})
                    for r in rows]


@router.post("/pipeline/sync", response_model=QueuedOut, status_code=202)
async def sync(user: dict = Depends(current_user), pool=Depends(arq), tid: str = Depends(trace_id)) -> QueuedOut:
    j = await pool.enqueue_job("sync_pipeline", user["id"])
    return QueuedOut(queued=j is not None, job="sync_pipeline", trace_id=tid)
