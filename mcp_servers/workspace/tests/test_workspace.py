from mcp_servers.testing import session
from mcp_servers.workspace.server import mcp


async def test_slots_and_idempotent_hold(tmp_path, monkeypatch):
    import mcp_servers.workspace.server as ws
    monkeypatch.setattr(ws, "DIR", tmp_path)
    async with session(mcp, user="u1") as s:
        slots = (await s.call_tool("free_slots", {"days_ahead": 5})).structuredContent["slots"]
        assert len(slots) == 3
        args = {"start": slots[0]["start"], "idempotency_key": "hold-key-0001"}
        h1 = (await s.call_tool("create_interview_hold", args)).structuredContent
        h2 = (await s.call_tool("create_interview_hold", args)).structuredContent
        assert h1["id"] == h2["id"]
        slots2 = (await s.call_tool("free_slots", {"days_ahead": 5})).structuredContent["slots"]
        assert slots2[0]["start"] != slots[0]["start"]  # the held slot is no longer free
