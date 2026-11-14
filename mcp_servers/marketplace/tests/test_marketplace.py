import os

import pytest
from fastapi.testclient import TestClient

os.environ["GIGSIM_DB"] = os.path.join(os.path.dirname(__file__), "_mk.sqlite")
from gigsim import server as gigsim  # noqa: E402
from mcp_servers.marketplace import server as mk  # noqa: E402
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter  # noqa: E402
from mcp_servers.testing import session  # noqa: E402

A = {"X-Admin-Key": "gigsim-admin"}


@pytest.fixture(autouse=True)
def gigsim_inprocess(tmp_path, monkeypatch):
    monkeypatch.setattr(gigsim, "DB_PATH", tmp_path / "gigsim.sqlite")
    gigsim.init_db(reset=True)
    gigsim._rate.clear()
    tc = TestClient(gigsim.app)
    tc.post("/admin/clock", json={"advance_minutes": 60 * 24 * 8}, headers=A)
    monkeypatch.setattr(mk, "_adapter", GigSimAdapter(http=tc))
    monkeypatch.setattr(mk, "_IDEM_DB", tmp_path / "idem.sqlite")
    yield tc


async def test_annotations_and_schemas():
    async with session(mk.mcp) as s:
        tools = {t.name: t for t in (await s.list_tools()).tools}
        assert tools["search_jobs"].annotations.readOnlyHint
        assert tools["submit_proposal"].annotations.destructiveHint
        assert tools["submit_proposal"].annotations.idempotentHint
        assert "idempotency_key" in tools["submit_proposal"].inputSchema["required"]
        assert tools["create_proposal_draft"].inputSchema["properties"]["cover_letter"]["minLength"] == 50


async def test_dry_run_then_idempotent_submit_spends_once():
    async with session(mk.mcp, user="ai_ml") as s:
        job = (await s.call_tool("search_jobs", {"limit": 1})).structuredContent["jobs"][0]
        args = {"job_id": job["id"], "cover_letter": "A grounded cover letter " * 5, "bid_amount": 40,
                "idempotency_key": "draft-key-001"}
        dry = await s.call_tool("create_proposal_draft", {**args, "dry_run": True})
        assert dry.structuredContent["dry_run"] and dry.structuredContent["result"]["would_create"]
        draft = (await s.call_tool("create_proposal_draft", args)).structuredContent["result"]
        before = (await s.call_tool("get_connects_balance", {})).structuredContent["balance"]
        sub = {"proposal_id": draft["id"], "idempotency_key": "submit-key-001"}
        r1 = (await s.call_tool("submit_proposal", sub)).structuredContent
        r2 = (await s.call_tool("submit_proposal", sub)).structuredContent
        after = (await s.call_tool("get_connects_balance", {})).structuredContent["balance"]
        assert r2["replayed"] and r1["result"] == r2["result"]
        assert before - after == r1["result"]["connects_spent"]


async def test_degraded_mode_reports_unavailable(monkeypatch):
    bad = GigSimAdapter(base_url="http://127.0.0.1:9")
    bad.backoff = 0.01
    monkeypatch.setattr(mk, "_adapter", bad)
    async with session(mk.mcp) as s:
        r = await s.call_tool("search_jobs", {"limit": 1})
        assert r.isError and "marketplace_unavailable" in r.content[0].text


async def test_audit_log_has_trace_id():
    async with session(mk.mcp, user="ai_ml", trace="trace-xyz") as s:
        await s.call_tool("get_connects_balance", {})
    assert any(r["trace_id"] == "trace-xyz" and r["tool"] == "get_connects_balance" for r in mk._audit.tail(20))
