"""Graph runtime: checkpointer + store factories, profiles, start / resume / stream.

Production uses the Postgres checkpointer (C6: approvals survive restarts) and a
Postgres-backed LangGraph store for long-term memory. Tests and evals use the
in-memory equivalents.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.memory import store as memory
from common.config import ROOT, env

PERSONAS = ROOT / "data" / "personas"


def persona_profile(tenant: str) -> dict:
    p = PERSONAS / tenant / "profile.json"
    return json.loads(p.read_text()) if p.exists() else {"name": "Freelancer", "rate_floor": 25, "hourly_rate": 35}


@asynccontextmanager
async def runtime(kind: str = "auto"):
    """Yields (bid_graph, conversation_graph). kind: postgres | memory | auto."""
    url = env("DATABASE_URL")
    if kind == "memory" or (kind == "auto" and not url):
        saver = InMemorySaver()
        yield build_bid_graph(saver, memory.get_store()), build_conversation_graph(saver, memory.get_store())
        return
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.store.postgres import PostgresStore
    from psycopg import Connection
    from psycopg.rows import dict_row
    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        await saver.setup()
        conn = Connection.connect(url, autocommit=True, prepare_threshold=0, row_factory=dict_row)
        store = PostgresStore(conn)
        store.setup()
        memory.set_store(store)
        try:
            yield build_bid_graph(saver, store), build_conversation_graph(saver, store)
        finally:
            conn.close()


def bid_thread_id(user_id: str, job_id: str) -> str:
    return f"bid:{user_id}:{job_id}"


def initial_bid_state(user_id: str, tenant: str, job: dict, profile: dict | None = None,
                      force_bid: bool = False, trace_id: str | None = None) -> dict:
    return {"user_id": user_id, "tenant": tenant, "job_id": job["id"], "job": job,
            "thread_id": bid_thread_id(user_id, job["id"]), "trace_id": trace_id or uuid.uuid4().hex,
            "profile": profile or persona_profile(tenant), "force_bid": force_bid, "status": "queued"}


def config_for(thread_id: str, trace_id: str = "", user_id: str = "", run_id: str | None = None) -> dict:
    from common.tracing import callbacks
    c = {"configurable": {"thread_id": thread_id}, "run_name": thread_id.split(":")[0] + "_graph",
         "metadata": {"trace_id": trace_id, "user_id": user_id, "thread_id": thread_id}, "tags": ["gigbid"],
         "recursion_limit": 60, "callbacks": callbacks()}
    if run_id:
        c["run_id"] = uuid.UUID(run_id)   # LangSmith root run id == our run id -> trace URL is known
    return c


async def stream_run(graph, inp: Any, cfg: dict) -> AsyncIterator[dict]:
    """Node-by-node progress events for the UI (SSE). Yields dicts."""
    async for mode, chunk in graph.astream(inp, cfg, stream_mode=["updates", "custom"]):
        if mode == "updates":
            for node_name, update in chunk.items():
                if node_name == "__interrupt__":
                    yield {"event": "interrupt", "node": "approval",
                           "payload_type": (update[0].value or {}).get("type") if update else None}
                    continue
                upd = update or {}
                yield {"event": "node", "node": node_name, "status": upd.get("status"),
                       "summary": summarize(node_name, upd),
                       "latency_s": next((t.get("latency_s") for t in upd.get("trace", []) if t.get("kind") == "node"), None),
                       "tokens": sum(u.get("input_tokens", 0) + u.get("output_tokens", 0)
                                     for u in (upd.get("usage") or {}).values())}
        else:
            yield {"event": "custom", **(chunk if isinstance(chunk, dict) else {"data": chunk})}


def summarize(node: str, upd: dict) -> str:
    if node == "analyst" and upd.get("job_spec"):
        return f"{len(upd['job_spec'].get('requirements', []))} requirements extracted"
    if node == "risk" and upd.get("risk"):
        r = upd["risk"]
        return f"risk {r.get('risk_score')} {'SCAM ' if r.get('is_scam') else ''}{','.join(r.get('flags', [])[:3])}"
    if node == "matcher" and upd.get("fit"):
        return f"fit {upd['fit'].get('fit_score')}"
    if node == "decide" and upd.get("decision"):
        return f"{upd['decision']['action']}: {'; '.join(upd['decision']['reasons'])[:120]}"
    if node == "pricing" and upd.get("price"):
        return f"${upd['price']['amount']} {upd['price']['unit']}"
    if node == "verifier" and upd.get("verification"):
        v = upd["verification"]
        return f"{v['claims_total']} claims, {v['unsupported_before']} unsupported removed"
    if node == "critic" and upd.get("critiques"):
        c = upd["critiques"][-1]
        return f"score {c['score']} {'approved' if c['approved'] else 'sent back'}"
    if node == "compliance" and upd.get("compliance"):
        return upd["compliance"]["verdict"]
    if node == "submit" and upd.get("submission"):
        return f"submitted {upd['submission'].get('proposal_id')}"
    if upd.get("errors"):
        return upd["errors"][-1][:120]
    return upd.get("status") or ""


async def resume(graph, thread_id: str, decision: dict, trace_id: str = "", user_id: str = ""):
    return await graph.ainvoke(Command(resume=decision), config_for(thread_id, trace_id, user_id))


async def pending_interrupt(graph, thread_id: str) -> dict | None:
    snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    for task in snap.tasks:
        for intr in task.interrupts:
            return intr.value
    return None
