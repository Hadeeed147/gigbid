"""Settings, saved searches, memory viewer, portfolio uploads, analytics, health."""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from agent.memory.store import delete_memory, list_memory
from apps.api import db
from apps.api.auth.security import current_user
from apps.api.deps import iso
from apps.api.schemas.models import (
    AnalyticsOut,
    HealthOut,
    MemoryOut,
    PortfolioItemIn,
    PortfolioItemOut,
    SavedSearchIn,
    SavedSearchOut,
    SettingsIn,
    UserOut,
)
from common.config import cfg
from rag.ingest.loaders import RawItem
from rag.retriever import get_store

router = APIRouter(tags=["settings", "analytics"])


@router.put("/settings", response_model=UserOut)
def update_settings(body: SettingsIn, user: dict = Depends(current_user)) -> UserOut:
    s = {**(user.get("settings") or {}), **body.model_dump(exclude_none=True)}
    db.q("UPDATE users SET settings=%s WHERE id=%s", (db.jb(s), user["id"]))
    u = db.one("SELECT * FROM users WHERE id=%s", (user["id"],))
    return UserOut(id=u["id"], email=u["email"], name=u["name"], tenant=u["tenant"], onboarded=u["onboarded"], settings=s)


@router.get("/settings/searches", response_model=list[SavedSearchOut])
def searches(user: dict = Depends(current_user)) -> list[SavedSearchOut]:
    return [SavedSearchOut(id=r["id"], query=r["query"], category=r["category"], interval_minutes=r["interval_minutes"],
                           last_run=iso(r["last_run"])) for r in db.q("SELECT * FROM saved_searches WHERE user_id=%s",
                                                                      (user["id"],))]


@router.post("/settings/searches", response_model=SavedSearchOut)
def add_search(body: SavedSearchIn, user: dict = Depends(current_user)) -> SavedSearchOut:
    sid = "s_" + uuid.uuid4().hex[:8]
    db.q("INSERT INTO saved_searches (id, user_id, query, category, interval_minutes) VALUES (%s,%s,%s,%s,%s)",
         (sid, user["id"], body.query, body.category, body.interval_minutes))
    return SavedSearchOut(id=sid, **body.model_dump())


@router.delete("/settings/searches/{sid}")
def delete_search(sid: str, user: dict = Depends(current_user)) -> dict:
    db.q("DELETE FROM saved_searches WHERE id=%s AND user_id=%s", (sid, user["id"]))
    return {"ok": True}


@router.get("/settings/memory", response_model=MemoryOut)
def memory(user: dict = Depends(current_user)) -> MemoryOut:
    return MemoryOut(**list_memory(user["id"]))


@router.delete("/settings/memory/{kind}/{key:path}")
def forget(kind: str, key: str, user: dict = Depends(current_user)) -> dict:
    if kind not in ("style", "outcome"):
        raise HTTPException(400, "kind must be style or outcome")
    if not delete_memory(user["id"], kind, key):
        raise HTTPException(404, "memory item not found")
    return {"ok": True}


@router.get("/portfolio/items", response_model=list[PortfolioItemOut])
def portfolio(user: dict = Depends(current_user)) -> list[PortfolioItemOut]:
    return [PortfolioItemOut(item_id=i.item_id, title=i.title, type=i.type, source=i.source)
            for i in get_store().items(user["tenant"]) if i.type != "proposal"]


@router.post("/portfolio/items", response_model=PortfolioItemOut)
def add_portfolio_item(body: PortfolioItemIn, user: dict = Depends(current_user)) -> PortfolioItemOut:
    """Add work in the UI; it is chunked and indexed incrementally (only the new chunks are embedded)."""
    tenant = user["tenant"]
    iid = f"{tenant}:{'cs' if body.type == 'case_study' else body.type}:u{uuid.uuid4().hex[:6]}"
    item = RawItem(item_id=iid, type=body.type, tenant=tenant, text=f"# {body.title}\n\n{body.text}", title=body.title,
                   project_id=f"{tenant}:user:{uuid.uuid4().hex[:6]}", date=date.today().isoformat(), source="user")
    n = get_store().add_item(item)
    return PortfolioItemOut(item_id=iid, title=body.title, type=body.type, source="user", chunks_indexed=n)


@router.delete("/portfolio/items/{item_id:path}")
def remove_portfolio_item(item_id: str, user: dict = Depends(current_user)) -> dict:
    if not item_id.startswith(user["tenant"] + ":"):
        raise HTTPException(404, "item not found")
    return {"removed_chunks": get_store().remove_item(user["tenant"], item_id)}


@router.get("/analytics", response_model=AnalyticsOut)
def analytics(user: dict = Depends(current_user)) -> AnalyticsOut:
    uid = user["id"]
    pipe = db.q("SELECT category, stage, connects_spent FROM pipeline WHERE user_id=%s", (uid,))
    cats: dict[str, Counter] = {}
    for p in pipe:
        c = cats.setdefault(p["category"] or "Other", Counter())
        c["sent"] += 1
        if p["stage"] in ("replied", "interview", "hired"):
            c["replied"] += 1
        if p["stage"] == "hired":
            c["hired"] += 1
    by_cat = [{"category": k, "sent": v["sent"], "reply_rate": round(v["replied"] / v["sent"], 3) if v["sent"] else 0,
               "hire_rate": round(v["hired"] / v["sent"], 3) if v["sent"] else 0} for k, v in cats.items()]
    spent = sum(p["connects_spent"] or 0 for p in pipe)
    wins = sum(1 for p in pipe if p["stage"] in ("replied", "interview", "hired"))
    inbox = db.q("SELECT usage, latency_s, status FROM inbox WHERE user_id=%s", (uid,))

    def tot(u: dict, k: str) -> float:
        return sum(n.get(k, 0) for n in (u or {}).values())
    analysed = [r for r in inbox if r["usage"]]
    proposals = [r for r in analysed if "writer" in (r["usage"] or {})]
    lat = sorted(r["latency_s"] or 0 for r in proposals)
    cost = {"jobs_analysed": len(analysed), "proposals": len(proposals),
            "avg_usd_per_job": round(sum(tot(r["usage"], "usd") for r in analysed) / max(1, len(analysed)), 5),
            "avg_usd_per_proposal": round(sum(tot(r["usage"], "usd") for r in proposals) / max(1, len(proposals)), 5),
            "p95_latency_s_per_proposal": lat[int(0.95 * (len(lat) - 1))] if lat else None,
            "avg_tokens_per_proposal": round(sum(tot(r["usage"], "input_tokens") + tot(r["usage"], "output_tokens")
                                                 for r in proposals) / max(1, len(proposals)))}
    reasons = Counter(r["reason"] for r in db.q("SELECT reason FROM approvals WHERE user_id=%s AND action='reject'", (uid,))
                      if r["reason"])
    funnel = Counter(r["status"] for r in inbox)
    return AnalyticsOut(by_category=by_cat, connects={"spent": spent, "replies_or_better": wins,
                                                      "connects_per_reply": round(spent / wins, 1) if wins else None},
                        cost_latency=cost, rejection_reasons=[{"reason": k, "count": v} for k, v in reasons.most_common(10)],
                        funnel=dict(funnel))


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    st = db.get_status("marketplace") or {"up": True, "reason": "not checked yet"}
    return HealthOut(api=True, marketplace=st, mode=cfg("marketplace.mode"), profile=cfg("active_profile"))
