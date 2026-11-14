"""Bid + conversation graphs end to end against an in-process GigSim, with the
deterministic test-double LLM (no API key). Covers: parallel analysis, scam skip,
interrupt + approve -> exactly-once submit, edit -> compliance re-check ->
style memory staging, reject with reason, bounded critic loop, resume after a
'crash' (fresh graph object on the same checkpointer), and a client reply."""
import json
import os

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

os.environ["GIGBID_FAKE_LLM"] = "1"
os.environ["GIGBID_MCP_TRANSPORT"] = "inprocess"

from agent import mcp_client  # noqa: E402
from agent.graphs.bid_graph import build_bid_graph  # noqa: E402
from agent.graphs.conversation_graph import build_conversation_graph  # noqa: E402
from agent.memory import store as memory  # noqa: E402
from agent.runtime import config_for, initial_bid_state, pending_interrupt  # noqa: E402
from gigsim import server as gigsim  # noqa: E402
from mcp_servers.marketplace import server as mk  # noqa: E402
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter  # noqa: E402

A = {"X-Admin-Key": "gigsim-admin"}
DEV = [json.loads(x) for x in open("evals/datasets/dev_ai_ml.jsonl", encoding="utf-8")]


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setattr(gigsim, "DB_PATH", tmp_path / "gs.sqlite")
    gigsim.init_db(reset=True)
    gigsim._rate.clear()
    tc = TestClient(gigsim.app)
    tc.post("/admin/clock", json={"advance_minutes": 60 * 24 * 8}, headers=A)
    monkeypatch.setattr(mk, "_adapter", GigSimAdapter(http=tc))
    monkeypatch.setattr(mk, "_IDEM_DB", tmp_path / "idem.sqlite")
    memory.set_store(InMemoryStore())
    await mcp_client.reset_hub()
    await mcp_client.get_hub("inprocess")
    yield tc
    await mcp_client.reset_hub()


def public(job):
    return {k: v for k, v in job.items() if k not in ("gold", "_hidden")}


def pick(kind):
    return next(j for j in DEV if j["gold"]["kind"] == kind and j["gold"]["bid"] == (kind == "fit")
                and not j["gold"].get("duplicate_of"))


async def run_to_interrupt(graph, job, user="u1"):
    st = initial_bid_state(user, "ai_ml", public(job))
    cfg = config_for(st["thread_id"])
    out = await graph.ainvoke(st, cfg)
    return st, cfg, out


async def test_scam_is_skipped(env):
    g = build_bid_graph(InMemorySaver())
    job = next(j for j in DEV if j["gold"]["kind"] == "scam" and "Telegram" in j["description"] or
               (j["gold"]["kind"] == "scam" and "WhatsApp" in j["description"]))
    _, _, out = await run_to_interrupt(g, job)
    assert out["decision"]["action"] == "skip" and out["status"] == "skipped"
    assert out["risk"]["is_scam"]
    # parallel branches all ran
    nodes = {t["node"] for t in out["trace"] if t.get("kind") == "node"}
    assert {"analyst", "risk", "matcher", "decide"} <= nodes


async def test_approve_submits_exactly_once_even_after_crash(env):
    saver = InMemorySaver()
    g = build_bid_graph(saver)
    job = pick("fit")
    st, cfg, out = await run_to_interrupt(g, job)
    assert out["status"] == "awaiting_approval", out.get("errors") or out.get("decision")
    payload = await pending_interrupt(g, st["thread_id"])
    assert payload["type"] == "proposal_approval" and payload["dry_run_preview"]["dry_run"]
    before = env.get("/me/connects", headers={"Authorization": "Bearer gs_ai_ml"}).json()["balance"]
    # "crash": a brand-new graph object on the same checkpointer resumes the thread
    g2 = build_bid_graph(saver)
    res = await g2.ainvoke(Command(resume={"action": "approve"}), cfg)
    assert res["status"] == "submitted"
    # replaying the submit node (e.g. worker crashed after the call) must not spend twice
    from agent.nodes.approval import submit
    again = await submit({**res, "status": "approved"})
    assert again["submission"]["replayed"] is True
    after = env.get("/me/connects", headers={"Authorization": "Bearer gs_ai_ml"}).json()["balance"]
    assert before - after == res["submission"]["connects_spent"]
    assert len([p for p in env.get("/proposals", headers={"Authorization": "Bearer gs_ai_ml"}).json()["proposals"]
                if p["status"] == "submitted"]) == 1


async def test_edit_rechecks_compliance_and_stages_style_memory(env):
    g = build_bid_graph(InMemorySaver())
    job = pick("fit")
    st, cfg, out = await run_to_interrupt(g, job, user="editor")
    edited = "I am passionate about this! " + out["draft"]["cover_letter"] + " Email me at me@example.com."
    out2 = await g.ainvoke(Command(resume={"action": "edit", "text": edited}), cfg)
    assert out2["status"] == "awaiting_approval"          # back at approval after compliance re-check
    assert "me@example.com" not in out2["draft"]["cover_letter"]
    assert "passionate" not in out2["draft"]["cover_letter"].lower()
    assert any(a["action"] == "edit" and a.get("diff") for a in out2["approvals"])


async def test_reject_with_reason(env):
    g = build_bid_graph(InMemorySaver())
    st, cfg, out = await run_to_interrupt(g, pick("fit"), user="rej")
    out2 = await g.ainvoke(Command(resume={"action": "reject", "reason": "too generic"}), cfg)
    assert out2["status"] == "rejected" and "too generic" in out2["attention_reason"]


async def test_critic_loop_is_bounded(env, monkeypatch):
    monkeypatch.setenv("GIGBID_FAKE_CRITIC_LOOP", "1")
    g = build_bid_graph(InMemorySaver())
    _, _, out = await run_to_interrupt(g, pick("fit"), user="loop")
    writer_runs = [t for t in out["trace"] if t.get("node") == "writer"]
    assert 2 <= len(writer_runs) <= 3
    assert out["critiques"][0]["approved"] is False


async def test_style_memory_promotion_rule():
    memory.set_store(InMemoryStore())
    memory.record_edit("m", "I am passionate about data. Here is my plan.", "Here is my plan.")
    assert memory.style_rules("m") == []          # one edit is not enough
    memory.record_edit("m", "I am passionate about apps. I built X.", "I built X.")
    rules = memory.style_rules("m")
    assert any("passionate" in r for r in rules)   # promoted after 2 distinct edits
    key = next(i["key"] for i in memory.list_memory("m")["style"] if "passionate" in i["rule"])
    assert memory.delete_memory("m", "style", key)
    memory.record_edit("m", "I am passionate again. Ok.", "Ok.")
    assert not any("passionate" in r for r in memory.style_rules("m"))  # deleted rules stay deleted


async def test_conversation_reply_flow(env):
    """Submit proposals until a simulated client replies (outcomes are deterministic per job+text)."""
    g = build_bid_graph(InMemorySaver())
    fits = [j for j in DEV if j["gold"]["kind"] == "fit" and j["gold"]["bid"] and not j["gold"].get("duplicate_of")]
    threads = []
    for job in fits[:12]:
        st, cfg, out = await run_to_interrupt(g, job, user="conv")
        if out.get("status") != "awaiting_approval":
            continue
        await g.ainvoke(Command(resume={"action": "approve"}), cfg)
        env.post("/admin/clock", json={"advance_minutes": 60 * 24 * 6}, headers=A)
        threads = env.get("/threads", headers={"Authorization": "Bearer gs_ai_ml"}).json()["threads"]
        if threads:
            break
    assert threads, "no simulated client replied to 12 proposals"
    cg = build_conversation_graph(InMemorySaver())
    ccfg = config_for("conv:" + threads[0]["id"])
    o = await cg.ainvoke({"user_id": "conv", "tenant": "ai_ml", "thread_id": threads[0]["id"],
                          "profile": {"name": "Sana", "rate_floor": 35}}, ccfg)
    assert o["status"] == "awaiting_approval" and o["reply"]["text"]
    o2 = await cg.ainvoke(Command(resume={"action": "approve"}), ccfg)
    assert o2["status"] == "sent"
