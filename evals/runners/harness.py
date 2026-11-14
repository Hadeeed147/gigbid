"""In-process eval harness: a fresh GigSim (all dev jobs released), in-process MCP
servers and the bid graph on an in-memory checkpointer. Used by every runner so
results are reproducible and nothing touches the deployed system.

The harness stops each thread at the approval interrupt. When a runner needs
marketplace outcomes it approves drafts itself; that is the EVALUATION HARNESS
standing in for a human, never a product behaviour (GigBid never auto-sends).
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

os.environ.setdefault("GIGBID_MCP_TRANSPORT", "inprocess")
os.environ.setdefault("GIGSIM_ERROR_RATE", "0")
os.environ.setdefault("GIGBID_SECRETS_BACKEND", "file")
os.environ["MCP_BEARER_TOKEN"] = ""

from fastapi.testclient import TestClient  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.store.memory import InMemoryStore  # noqa: E402
from langgraph.types import Command  # noqa: E402

from agent import mcp_client  # noqa: E402
from agent.graphs.bid_graph import build_bid_graph  # noqa: E402
from agent.memory import store as memory  # noqa: E402
from agent.nodes.scout import fingerprint  # noqa: E402
from agent.runtime import config_for, initial_bid_state, persona_profile  # noqa: E402
from evals.runners.common import public  # noqa: E402
from gigsim import server as gigsim  # noqa: E402

A = {"X-Admin-Key": "gigsim-admin"}


@asynccontextmanager
async def harness(policy_version: int = 1):
    tmp = Path(tempfile.mkdtemp(prefix="gigbid-eval-"))
    gigsim.DB_PATH = tmp / "gigsim.sqlite"
    gigsim.init_db(reset=True)
    gigsim._rate.clear()
    gigsim.RATE_LIMIT = 10_000          # the eval is not testing GigSim's limiter
    tc = TestClient(gigsim.app)
    tc.post("/admin/clock", json={"advance_minutes": 60 * 24 * 8}, headers=A)
    tc.post("/admin/policy", json={"version": policy_version}, headers=A)
    from mcp_servers.marketplace import server as mk
    from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
    mk._adapter = GigSimAdapter(http=tc)
    mk._IDEM_DB = tmp / "idem.sqlite"
    memory.set_store(InMemoryStore())
    await mcp_client.reset_hub()
    await mcp_client.get_hub("inprocess")
    try:
        yield Harness(tc)
    finally:
        await mcp_client.reset_hub()


class Harness:
    def __init__(self, tc: TestClient):
        self.tc = tc
        self.graph = build_bid_graph(InMemorySaver(), memory.get_store())
        self.seen_fp: dict[str, set[str]] = {}

    async def analyse(self, persona: str, job: dict, user: str | None = None) -> dict:
        """Run one job to the approval interrupt (or to skip/watch). Returns final state + wall time."""
        user = user or f"eval-{persona}"
        pj = public(job)
        fps = self.seen_fp.setdefault(user, set())
        fp = fingerprint(pj)
        if fp in fps:
            pj["_duplicate"] = True        # what the Scout would have flagged
        fps.add(fp)
        st = initial_bid_state(user, persona, pj, persona_profile(persona))
        t0 = time.time()
        out = await self.graph.ainvoke(st, config_for(st["thread_id"]))
        out["_wall_s"] = time.time() - t0
        out["_thread_id"] = st["thread_id"]
        return out

    async def approve(self, thread_id: str) -> dict:
        return await self.graph.ainvoke(Command(resume={"action": "approve"}), config_for(thread_id))

    def outcomes(self, token: str) -> dict:
        self.tc.post("/admin/clock", json={"advance_minutes": 60 * 24 * 7}, headers=A)
        return self.tc.get("/admin/outcomes", params={"token": token}, headers=A).json()


async def gather_limited(coros, limit: int = 3):
    sem = asyncio.Semaphore(limit)

    async def one(c):
        async with sem:
            return await c
    return await asyncio.gather(*(one(c) for c in coros), return_exceptions=True)
