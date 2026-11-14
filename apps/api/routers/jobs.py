"""Job inbox and job detail."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from apps.api import db
from apps.api.auth.security import current_user
from apps.api.deps import PRIORITY, arq, graphs, iso, trace_id
from apps.api.schemas.models import InboxItem, InboxOut, JobDetail, QueuedOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _item(r: dict) -> InboxItem:
    return InboxItem(**{**{k: r.get(k) for k in InboxItem.model_fields}, "flags": r.get("flags") or [],
                        "reasons": r.get("reasons") or [], "is_scam": bool(r.get("is_scam")),
                        "updated_at": iso(r.get("updated_at"))})


@router.get("", response_model=InboxOut)
def inbox(user: dict = Depends(current_user), action: str | None = None, status: str | None = None,
          min_fit: float = Query(0, ge=0, le=1), q: str = "", hide_skipped: bool = False,
          limit: int = Query(100, le=500)) -> InboxOut:
    sql = "SELECT * FROM inbox WHERE user_id=%(u)s AND COALESCE(fit,0) >= %(f)s"
    p: dict = {"u": user["id"], "f": min_fit}
    if action:
        sql += " AND action=%(a)s"
        p["a"] = action
    if status:
        sql += " AND status=%(s)s"
        p["s"] = status
    if hide_skipped:
        sql += " AND COALESCE(action,'') <> 'skip'"
    if q:
        sql += " AND title ILIKE %(q)s"
        p["q"] = f"%{q}%"
    sql += (" ORDER BY (status='awaiting_approval') DESC, CASE action WHEN 'bid' THEN 0 WHEN 'watch' THEN 1 ELSE 2 END,"
            " fit DESC NULLS LAST, updated_at DESC LIMIT %(l)s")
    p["l"] = limit
    rows = db.q(sql, p)
    return InboxOut(items=[_item(r) for r in rows], total=len(rows))


@router.get("/{job_id}", response_model=JobDetail)
async def detail(job_id: str, user: dict = Depends(current_user), g=Depends(graphs)) -> JobDetail:
    r = db.one("SELECT * FROM inbox WHERE user_id=%s AND job_id=%s", (user["id"], job_id))
    if not r:
        raise HTTPException(404, "job not in your inbox")
    snap = await g[0].aget_state({"configurable": {"thread_id": r["thread_id"]}})
    v = snap.values or {}
    return JobDetail(item=_item(r), job=v.get("job") or {"id": job_id, "title": r["title"]}, job_spec=v.get("job_spec"),
                     risk=v.get("risk"), fit=v.get("fit"), evidence=v.get("evidence") or {}, decision=v.get("decision"),
                     price=v.get("price"), usage=v.get("usage") or {}, status=v.get("status"))


@router.post("/{job_id}/skip", response_model=InboxItem)
def skip(job_id: str, user: dict = Depends(current_user)) -> InboxItem:
    db.q("UPDATE inbox SET status='skipped', action='skip', reasons=reasons || %s, updated_at=now() "
         "WHERE user_id=%s AND job_id=%s", (db.jb(["skipped by you"]), user["id"], job_id))
    r = db.one("SELECT * FROM inbox WHERE user_id=%s AND job_id=%s", (user["id"], job_id))
    if not r:
        raise HTTPException(404, "job not in your inbox")
    return _item(r)


@router.post("/{job_id}/draft", response_model=QueuedOut, status_code=202)
async def draft_anyway(job_id: str, user: dict = Depends(current_user), g=Depends(graphs), pool=Depends(arq),
                       tid: str = Depends(trace_id)) -> QueuedOut:
    """Override a skip/watch: run the bid graph with force_bid (still requires approval before sending)."""
    r = db.one("SELECT * FROM inbox WHERE user_id=%s AND job_id=%s", (user["id"], job_id))
    if not r:
        raise HTTPException(404, "job not in your inbox")
    snap = await g[0].aget_state({"configurable": {"thread_id": r["thread_id"]}})
    job = (snap.values or {}).get("job")
    if not job:
        raise HTTPException(409, "job not analysed yet")
    j = await pool.enqueue_job("analyse_job", user["id"], job, True, tid, **PRIORITY, _job_id=f"force:{user['id']}:{job_id}")
    return QueuedOut(queued=j is not None, job="analyse_job", trace_id=tid)


@router.post("/scout", response_model=QueuedOut, status_code=202)
async def scout_now(user: dict = Depends(current_user), pool=Depends(arq), tid: str = Depends(trace_id)) -> QueuedOut:
    j = await pool.enqueue_job("scout_user", user["id"], True, _job_id=f"scout-now:{user['id']}:{uuid.uuid4().hex[:6]}")
    return QueuedOut(queued=j is not None, job="scout_user", trace_id=tid)
