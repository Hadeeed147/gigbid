"""Arq tasks: scouting on schedules, bid/conversation runs, approval resumes,
pipeline sync, degraded-mode recovery. Long agent work never runs in a web request.

Idempotency (E1):
  * Arq job ids are deterministic (analyse:<user>:<job>), so a job is enqueued once.
  * A thread that already has a checkpoint is never re-analysed (worker restarts).
  * Submission uses idempotency keys derived from the thread id (see agent/nodes/approval.py).
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime

from langgraph.types import Command

from agent.mcp_client import get_hub, run_identity
from agent.memory.store import record_outcome
from agent.nodes._runtime import DegradedError
from agent.nodes.scout import fingerprint, run_saved_search
from agent.runtime import bid_thread_id, config_for, initial_bid_state, persona_profile, stream_run
from apps.api import db
from common.config import cfg
from common.tracing import trace_url
from worker.events import publish


# ------------------------------------------------------------------ helpers
def profile_for(user: dict) -> dict:
    base = persona_profile(user["tenant"])
    s = user.get("settings") or {}
    return {**base, "name": s.get("display_name") or base.get("name") or user["name"],
            "rate_floor": s.get("rate_floor", base.get("rate_floor", 25)),
            "hourly_rate": s.get("hourly_rate", base.get("hourly_rate", 35)),
            "autonomy": s.get("autonomy", "suggest_only"),
            "weekly_connects_budget": s.get("weekly_connects_budget", 60)}


def get_user(user_id: str) -> dict:
    return db.one("SELECT id, email, name, tenant, settings FROM users WHERE id=%s", (user_id,))


def sync_inbox(user_id: str, job: dict, thread_id: str, st: dict, trace_id: str = "", run_id: str = "") -> None:
    risk, fit, dec, price = st.get("risk") or {}, st.get("fit") or {}, st.get("decision") or {}, st.get("price")
    usage = st.get("usage") or {}
    latency = sum(t.get("latency_s", 0) for t in st.get("trace", []) if t.get("kind") == "node")
    db.q("""INSERT INTO inbox (user_id, job_id, thread_id, title, category, status, action, fit, risk, is_scam, flags,
              price, connects_cost, budget, reasons, attention_reason, usage, latency_s, trace_id, trace_url, proposal_id,
              updated_at)
            VALUES (%(u)s,%(j)s,%(t)s,%(title)s,%(cat)s,%(status)s,%(action)s,%(fit)s,%(risk)s,%(scam)s,%(flags)s,%(price)s,
              %(cc)s,%(budget)s,%(reasons)s,%(att)s,%(usage)s,%(lat)s,%(trace)s,%(turl)s,%(pid)s,now())
            ON CONFLICT (user_id, job_id) DO UPDATE SET status=excluded.status, action=excluded.action, fit=excluded.fit,
              risk=excluded.risk, is_scam=excluded.is_scam, flags=excluded.flags, price=excluded.price,
              reasons=excluded.reasons, attention_reason=excluded.attention_reason, usage=excluded.usage,
              latency_s=excluded.latency_s, trace_id=COALESCE(excluded.trace_id, inbox.trace_id),
              trace_url=COALESCE(excluded.trace_url, inbox.trace_url),
              proposal_id=COALESCE(excluded.proposal_id, inbox.proposal_id), updated_at=now()""",
         {"u": user_id, "j": job["id"], "t": thread_id, "title": job.get("title", "")[:300], "cat": job.get("category"),
          "status": st.get("status") or "queued", "action": dec.get("action"), "fit": fit.get("fit_score"),
          "risk": risk.get("risk_score"), "scam": bool(risk.get("is_scam")), "flags": db.jb(risk.get("flags", [])),
          "price": db.jb(price) if price else None, "cc": job.get("connects_cost"), "budget": db.jb(job.get("budget")),
          "reasons": db.jb(dec.get("reasons", [])), "att": st.get("attention_reason"), "usage": db.jb(usage),
          "lat": round(latency, 2), "trace": trace_id or st.get("trace_id"),
          "turl": trace_url(run_id) if run_id else None,
          "pid": (st.get("submission") or {}).get("proposal_id")})


async def _run(ctx, graph, inp, thread_id: str, user_id: str, trace_id: str, kind: str) -> dict:
    run_id = str(uuid.uuid4())
    db.q("INSERT INTO runs (id, user_id, thread_id, kind, status, trace_id) VALUES (%s,%s,%s,%s,'running',%s)",
         (run_id, user_id, thread_id, kind, trace_id))
    publish(thread_id, user_id, {"event": "run_started", "run_id": run_id, "kind": kind})
    status, err = "done", None
    try:
        async for ev in stream_run(graph, inp, config_for(thread_id, trace_id, user_id, run_id=run_id)):
            publish(thread_id, user_id, {**ev, "run_id": run_id})
        db.set_status("marketplace", {"up": True})
    except DegradedError as e:
        status, err = "degraded", str(e)
        db.set_status("marketplace", {"up": False, "reason": str(e)[:200]})
        publish(thread_id, user_id, {"event": "degraded", "message": "Marketplace unavailable: work is queued and "
                                                                     "will resume automatically."})
        await ctx["redis"].enqueue_job("retry_thread", user_id, thread_id, kind, trace_id,
                                       _job_id=f"retry:{thread_id}:{int(time.time() // 60)}", _defer_by=60)
    except Exception as e:  # noqa: BLE001 - surface any failure on the run timeline
        status, err = "error", f"{type(e).__name__}: {e}"[:500]
    url = trace_url(run_id)
    db.q("UPDATE runs SET status=%s, finished_at=now(), error=%s, trace_url=%s WHERE id=%s", (status, err, url, run_id))
    snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    publish(thread_id, user_id, {"event": "run_finished", "run_id": run_id, "status": status, "error": err,
                                 "trace_url": url, "graph_status": (snap.values or {}).get("status")})
    return {"values": snap.values or {}, "run_id": run_id, "status": status}


# ------------------------------------------------------------------ bid graph
async def analyse_job(ctx, user_id: str, job: dict, force_bid: bool = False, trace_id: str | None = None) -> str:
    bid, _ = ctx["graphs"]
    user = get_user(user_id)
    thread_id = bid_thread_id(user_id, job["id"])
    snap = await bid.aget_state({"configurable": {"thread_id": thread_id}})
    if snap.values and not force_bid:
        return "already analysed"                      # idempotent across worker restarts
    if snap.values and force_bid:
        thread_id = thread_id + ":forced"
    st = initial_bid_state(user_id, user["tenant"], job, profile_for(user), force_bid=force_bid, trace_id=trace_id)
    st["thread_id"] = thread_id
    sync_inbox(user_id, job, thread_id, {"status": "analysing", "trace_id": st["trace_id"]})
    out = await _run(ctx, bid, st, thread_id, user_id, st["trace_id"], "bid")
    sync_inbox(user_id, job, thread_id, out["values"], st["trace_id"], out["run_id"])
    return out["values"].get("status") or out["status"]


async def resume_bid(ctx, user_id: str, thread_id: str, decision: dict, trace_id: str = "") -> str:
    bid, _ = ctx["graphs"]
    db.q("INSERT INTO approvals (user_id, thread_id, kind, action, reason) VALUES (%s,%s,'proposal',%s,%s)",
         (user_id, thread_id, decision["action"], decision.get("reason")))
    out = await _run(ctx, bid, Command(resume=decision), thread_id, user_id, trace_id, "bid_resume")
    v = out["values"]
    if v.get("job"):
        sync_inbox(user_id, v["job"], thread_id, v, trace_id, out["run_id"])
    if v.get("status") == "submitted":
        sub = v["submission"]
        db.q("""INSERT INTO pipeline (user_id, proposal_id, job_id, title, category, stage, connects_spent)
                VALUES (%s,%s,%s,%s,%s,'submitted',%s) ON CONFLICT (user_id, proposal_id) DO NOTHING""",
             (user_id, sub["proposal_id"], v["job"]["id"], v["job"].get("title"), v["job"].get("category"),
              sub.get("connects_spent", 0)))
    edit = next((a for a in reversed(v.get("approvals", [])) if a.get("action") == "edit"), None)
    if edit and decision["action"] == "edit":
        db.q("UPDATE approvals SET diff=%s WHERE id=(SELECT max(id) FROM approvals WHERE thread_id=%s)",
             (edit.get("diff"), thread_id))
    return v.get("status") or out["status"]


async def retry_thread(ctx, user_id: str, thread_id: str, kind: str, trace_id: str = "") -> str:
    """Degraded-mode recovery: continue the same thread from its last good checkpoint."""
    bid, conv = ctx["graphs"]
    graph = conv if kind.startswith("conv") else bid
    out = await _run(ctx, graph, None, thread_id, user_id, trace_id, kind + "_retry")
    v = out["values"]
    if v.get("job") and not kind.startswith("conv"):
        sync_inbox(user_id, v["job"], thread_id, v, trace_id, out["run_id"])
    return out["status"]


# ------------------------------------------------------------------ scouting
async def scout_user(ctx, user_id: str, force: bool = False) -> int:
    user = get_user(user_id)
    searches = db.q("SELECT * FROM saved_searches WHERE user_id=%s", (user_id,))
    mode = cfg("marketplace.mode", "gigsim")
    floor_interval = cfg(f"marketplace.scout_interval_minutes.{mode}", 10)
    queued = 0
    tok = run_identity.set((user_id, uuid.uuid4().hex, user["tenant"]))
    try:
        for s in searches:
            interval = max(s["interval_minutes"], floor_interval)   # never poll faster than the policy allows
            if not force and s["last_run"] and (datetime.now(UTC) - s["last_run"]).total_seconds() < interval * 60:
                continue
            seen = {r["job_id"] for r in db.q("SELECT job_id FROM seen_jobs WHERE user_id=%s", (user_id,))}
            fps = {r["fingerprint"] for r in db.q("SELECT fingerprint FROM seen_jobs WHERE user_id=%s", (user_id,))}
            try:
                jobs = await run_saved_search(s, seen, fps, limit=10)
            except Exception as e:  # noqa: BLE001
                db.set_status("marketplace", {"up": False, "reason": str(e)[:200]})
                return 0
            db.q("UPDATE saved_searches SET last_run=now() WHERE id=%s", (s["id"],))
            for job in jobs:
                db.q("INSERT INTO seen_jobs (user_id, job_id, fingerprint) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                     (user_id, job["id"], fingerprint(job)))
                await ctx["redis"].enqueue_job("analyse_job", user_id, job, _job_id=f"analyse:{user_id}:{job['id']}")
                queued += 1
    finally:
        run_identity.reset(tok)
    return queued


async def scout_all(ctx) -> int:
    n = 0
    for u in db.q("SELECT id FROM users WHERE onboarded"):
        n += await scout_user(ctx, u["id"])
    return n


# ------------------------------------------------------------------ pipeline + conversations
STAGES = {"submitted": "submitted", "viewed": "viewed", "replied": "replied", "interview": "interview",
          "hired": "hired", "lost": "lost"}


async def sync_pipeline(ctx, user_id: str) -> int:
    user = get_user(user_id)
    cur = db.one("SELECT event_seq FROM cursors WHERE user_id=%s", (user_id,))
    after = cur["event_seq"] if cur else 0
    hub = await get_hub()
    tok = run_identity.set((user_id, uuid.uuid4().hex, user["tenant"]))
    try:
        events = (await hub.call("pipeline", "list_events", {"after_seq": after}))["items"]
    except Exception as e:  # noqa: BLE001
        db.set_status("marketplace", {"up": False, "reason": str(e)[:200]})
        return 0
    finally:
        run_identity.reset(tok)
    db.set_status("marketplace", {"up": True})
    for ev in events:
        stage = STAGES.get(ev["type"])
        row = db.one("SELECT * FROM pipeline WHERE user_id=%s AND proposal_id=%s", (user_id, ev["proposal_id"]))
        if stage and row:
            db.q("UPDATE pipeline SET stage=%s, thread_id=COALESCE(%s, thread_id), updated_at=now() "
                 "WHERE user_id=%s AND proposal_id=%s", (stage, ev.get("thread_id"), user_id, ev["proposal_id"]))
            publish(f"pipeline:{user_id}", user_id, {"event": "pipeline", "proposal_id": ev["proposal_id"], "stage": stage})
            if stage in ("replied", "interview", "hired", "lost"):
                inbox = db.one("SELECT * FROM inbox WHERE user_id=%s AND proposal_id=%s", (user_id, ev["proposal_id"]))
                record_outcome(user_id, {"proposal_id": ev["proposal_id"], "category": row.get("category"),
                                         "outcome": "ignored" if stage == "lost" else stage,
                                         "n_citations": len((inbox or {}).get("reasons") or [])})
        if ev["type"] == "replied" and ev.get("thread_id"):
            db.q("""INSERT INTO conversations (user_id, thread_id, job_id, title, status) VALUES (%s,%s,%s,%s,'new')
                    ON CONFLICT DO NOTHING""", (user_id, ev["thread_id"], ev["job_id"], row.get("title") if row else ""))
            await ctx["redis"].enqueue_job("run_conversation", user_id, ev["thread_id"],
                                           _job_id=f"conv:{user_id}:{ev['thread_id']}:{ev['seq']}")
        after = max(after, ev["seq"])
    db.q("INSERT INTO cursors (user_id, event_seq) VALUES (%s,%s) ON CONFLICT (user_id) DO UPDATE SET event_seq=%s",
         (user_id, after, after))
    return len(events)


async def sync_all(ctx) -> None:
    for u in db.q("SELECT id FROM users WHERE onboarded"):
        await sync_pipeline(ctx, u["id"])


def conv_thread_id(user_id: str, thread_id: str) -> str:
    return f"conv:{user_id}:{thread_id}"


async def run_conversation(ctx, user_id: str, thread_id: str, trace_id: str | None = None) -> str:
    _, conv = ctx["graphs"]
    user = get_user(user_id)
    tid = conv_thread_id(user_id, thread_id)
    snap = await conv.aget_state({"configurable": {"thread_id": tid}})
    if snap.values and snap.values.get("status") == "awaiting_approval":
        return "already awaiting approval"
    trace_id = trace_id or uuid.uuid4().hex
    row = db.one("SELECT job_id FROM conversations WHERE user_id=%s AND thread_id=%s", (user_id, thread_id))
    job = {}
    if row and row.get("job_id"):
        ib = db.one("SELECT title, category FROM inbox WHERE user_id=%s AND job_id=%s", (user_id, row["job_id"]))
        job = ib or {}
    inp = {"user_id": user_id, "tenant": user["tenant"], "thread_id": thread_id, "trace_id": trace_id,
           "profile": profile_for(user), "job": job, "status": "new"}
    if snap.values:   # new client message on an existing conversation: start a fresh cycle
        tid = f"{tid}:{int(time.time())}"
    out = await _run(ctx, conv, inp, tid, user_id, trace_id, "conversation")
    v = out["values"]
    last = (v.get("messages") or [{}])[-1]
    db.q("UPDATE conversations SET status=%s, intent=%s, last_message=%s, updated_at=now() WHERE user_id=%s AND thread_id=%s",
         (v.get("status"), (v.get("intent") or {}).get("intent"), last.get("text"), user_id, thread_id))
    db.set_status(f"conv_thread:{user_id}:{thread_id}", {"graph_thread": tid})
    return v.get("status") or out["status"]


async def resume_conversation(ctx, user_id: str, thread_id: str, decision: dict, trace_id: str = "") -> str:
    _, conv = ctx["graphs"]
    tid = (db.get_status(f"conv_thread:{user_id}:{thread_id}") or {}).get("graph_thread", conv_thread_id(user_id, thread_id))
    db.q("INSERT INTO approvals (user_id, thread_id, kind, action, reason) VALUES (%s,%s,'message',%s,%s)",
         (user_id, tid, decision["action"], decision.get("reason")))
    out = await _run(ctx, conv, Command(resume=decision), tid, user_id, trace_id, "conversation_resume")
    db.q("UPDATE conversations SET status=%s, updated_at=now() WHERE user_id=%s AND thread_id=%s",
         (out["values"].get("status"), user_id, thread_id))
    return out["values"].get("status") or out["status"]


async def ingest_github(ctx, user_id: str, login: str) -> dict:
    """Pull the user's repos through the official GitHub MCP server into their portfolio."""
    from rag.ingest.github import ingest
    user = get_user(user_id)
    return await ingest(user["tenant"], login)


async def health_check(ctx) -> dict:
    """Marketplace reachability for the UI's degraded-mode banner."""
    hub = await get_hub()
    tok = run_identity.set(("health", "", "ai_ml"))
    try:
        await hub.call("pricing", "get_policy", {})
        st = {"up": True}
    except Exception as e:  # noqa: BLE001
        st = {"up": False, "reason": str(e)[:200]}
    finally:
        run_identity.reset(tok)
    db.set_status("marketplace", st)
    return st


def dumps(o) -> str:
    return json.dumps(o, default=str)
