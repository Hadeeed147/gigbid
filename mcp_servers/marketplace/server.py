"""Marketplace MCP server (read + write), wrapping the marketplace port.

- Read tools: search_jobs, get_job, get_client_history, get_connects_balance,
  get_policy, get_market_stats, list_threads, list_messages, list_events.
- Write tools: create_proposal_draft, submit_proposal, send_message. Each has a
  constrained Pydantic input schema, a declared output schema, correct
  annotations, a required idempotency key and a dry_run flag.
- Bearer auth on HTTP, per-user rate limiter below GigSim's limit, append-only
  audit log (user, tool, arguments, result, trace id).

Run (HTTP):  uv run python -m mcp_servers.marketplace.server --port 8202
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import threading
from typing import Annotated, Any

import anyio
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from agent.marketplace_port import MarketplaceRejected, MarketplaceUnavailable, get_adapter
from common.config import ROOT, cfg
from mcp_servers.common import AuditLog, RateLimiter, auth_kwargs, caller

PORT = 8202
mcp = FastMCP("gigbid-marketplace", instructions=(
    "Marketplace tools for GigBid. All writes require an idempotency_key and are only called after the user "
    "approved them in GigBid. Use dry_run=true to preview exactly what would be sent and what it costs."),
    port=PORT, host="0.0.0.0", stateless_http=True, json_response=True, **auth_kwargs(PORT))

_adapter = None
_limiter = RateLimiter()
_audit = AuditLog("marketplace")
_idem_lock = threading.Lock()
_IDEM_DB = ROOT / "data" / "processed" / "marketplace_idempotency.sqlite"

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)


def adapter():
    global _adapter
    if _adapter is None:
        _adapter = get_adapter()
    return _adapter


def _idem(key: str, value: dict | None = None) -> dict | None:
    _IDEM_DB.parent.mkdir(parents=True, exist_ok=True)
    with _idem_lock:
        con = sqlite3.connect(_IDEM_DB)
        con.execute("CREATE TABLE IF NOT EXISTS idem (key TEXT PRIMARY KEY, result TEXT)")
        if value is None:
            row = con.execute("SELECT result FROM idem WHERE key=?", (key,)).fetchone()
            con.close()
            return json.loads(row[0]) if row else None
        con.execute("INSERT OR IGNORE INTO idem VALUES (?,?)", (key, json.dumps(value)))
        con.commit()
        con.close()
        return value


def account_for(user: str, tenant: str) -> str:
    """The marketplace account to act as: the user's own connected account, else the persona's seeded one."""
    from common import token_store
    try:
        if token_store.get(user, "gigsim") or token_store.get(user, "upwork_oauth"):
            return user
    except Exception:
        pass
    return tenant or user


async def _run(ctx: Context | None, tool: str, args: dict, fn) -> Any:
    user, trace, tenant = caller(ctx)
    user = account_for(user, tenant)
    await anyio.to_thread.run_sync(_limiter.wait, user)
    try:
        result = await anyio.to_thread.run_sync(lambda: fn(user))
    except MarketplaceUnavailable as e:
        _audit.write(user=user, tool=tool, args=args, result={"error": str(e)}, trace_id=trace, ok=False)
        raise ToolError(f"marketplace_unavailable: {e}") from e
    except MarketplaceRejected as e:
        _audit.write(user=user, tool=tool, args=args, result={"error": str(e)}, trace_id=trace, ok=False)
        raise ToolError(f"marketplace_rejected ({e.status}): {e.detail}") from e
    dump = result.model_dump() if isinstance(result, BaseModel) else (
        [r.model_dump() if isinstance(r, BaseModel) else r for r in result] if isinstance(result, list) else result)
    _audit.write(user=user, tool=tool, args=args, result=dump, trace_id=trace)
    return result


# ---------------------------------------------------------------------------
# Output schemas
# ---------------------------------------------------------------------------
class JobOut(BaseModel):
    id: str
    title: str
    description: str
    category: str | None = None
    budget: dict | None = None
    client_id: str | None = None
    screening_questions: list[str] = []
    connects_cost: int | None = None
    posted_at: str | None = None
    source: str | None = None


class JobList(BaseModel):
    jobs: list[JobOut]


class ClientOut(BaseModel):
    id: str
    name: str | None = None
    country: str | None = None
    industry: str | None = None
    payment_verified: bool | None = None
    total_spent: float | None = None
    hires: int | None = None
    jobs_posted: int | None = None
    avg_rating_given: float | None = None
    member_since: str | None = None
    reviews_from_freelancers: list[str] = []


class Balance(BaseModel):
    balance: int


class MarketStats(BaseModel):
    category: str
    hourly_p25: float
    hourly_p50: float
    hourly_p75: float
    fixed_p50: float | None = None
    source: str


class ListOut(BaseModel):
    items: list[dict]


class WriteResult(BaseModel):
    dry_run: bool = False
    idempotency_key: str
    replayed: bool = False
    result: dict


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------
@mcp.tool(annotations=READ, title="Search jobs")
async def search_jobs(
    query: Annotated[str, Field(description="Keywords, space separated", max_length=200)] = "",
    category: Annotated[str, Field(description="Exact category name or empty", max_length=80)] = "",
    posted_after: Annotated[str, Field(description="ISO timestamp; only newer jobs", max_length=40)] = "",
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ctx: Context | None = None,
) -> JobList:
    """Search open jobs on the connected marketplace, newest first."""
    args = {"query": query, "category": category, "posted_after": posted_after, "limit": limit}
    jobs = await _run(ctx, "search_jobs", args,
                      lambda u: adapter().search_jobs(u, query, category, posted_after, limit))
    return JobList(jobs=[JobOut(**j.model_dump(mode="json")) for j in jobs])


@mcp.tool(annotations=READ, title="Get job")
async def get_job(job_id: Annotated[str, Field(min_length=1, max_length=64)], ctx: Context | None = None) -> JobOut:
    """Full job post with budget, screening questions and Connects cost."""
    j = await _run(ctx, "get_job", {"job_id": job_id}, lambda u: adapter().get_job(u, job_id))
    return JobOut(**j.model_dump(mode="json"))


@mcp.tool(annotations=READ, title="Get client history")
async def get_client_history(client_id: Annotated[str, Field(min_length=1, max_length=64)],
                             ctx: Context | None = None) -> ClientOut:
    """Public client history: payment verification, spend, hires, ratings, reviews from freelancers."""
    c = await _run(ctx, "get_client_history", {"client_id": client_id},
                   lambda u: adapter().get_client_history(u, client_id))
    return ClientOut(**c.model_dump())


@mcp.tool(annotations=READ, title="Get Connects balance")
async def get_connects_balance(ctx: Context | None = None) -> Balance:
    """The freelancer's remaining Connects."""
    return Balance(balance=await _run(ctx, "get_connects_balance", {}, lambda u: adapter().get_connects_balance(u)))


@mcp.tool(annotations=READ, title="Get platform policy")
async def get_policy(ctx: Context | None = None) -> dict:
    """Current platform policy (version, Connects pricing, required submission fields, limits)."""
    return await _run(ctx, "get_policy", {}, lambda u: adapter().get_policy(u))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
          title="Get market statistics")
async def get_market_stats(category: Annotated[str, Field(max_length=80)] = "", ctx: Context | None = None) -> MarketStats:
    """Hourly-rate quantiles for a job category from historical postings (Kaggle Upwork data)."""
    path = ROOT / "data" / "processed" / "market_stats.json"
    stats = json.loads(path.read_text()) if path.exists() else {}
    s = stats.get(category) or stats.get("_default") or {"hourly_p25": 20, "hourly_p50": 35, "hourly_p75": 60,
                                                         "source": "synthetic-default"}
    return MarketStats(category=category or "_default", hourly_p25=s["hourly_p25"], hourly_p50=s["hourly_p50"],
                       hourly_p75=s["hourly_p75"], fixed_p50=s.get("fixed_p50"), source=s.get("source", "kaggle"))


@mcp.tool(annotations=READ, title="List conversation threads")
async def list_threads(ctx: Context | None = None) -> ListOut:
    """Client conversation threads for this freelancer."""
    return ListOut(items=await _run(ctx, "list_threads", {}, lambda u: adapter().list_threads(u)))


@mcp.tool(annotations=READ, title="List messages")
async def list_messages(thread_id: Annotated[str, Field(min_length=1, max_length=64)],
                        ctx: Context | None = None) -> ListOut:
    """Messages in one client thread, oldest first."""
    return ListOut(items=await _run(ctx, "list_messages", {"thread_id": thread_id},
                                    lambda u: adapter().list_messages(u, thread_id)))


@mcp.tool(annotations=READ, title="List marketplace events")
async def list_events(after_seq: Annotated[int, Field(ge=0)] = 0, ctx: Context | None = None) -> ListOut:
    """Proposal lifecycle events (submitted, viewed, replied, interview, hired, lost) after a sequence number."""
    return ListOut(items=await _run(ctx, "list_events", {"after_seq": after_seq},
                                    lambda u: adapter().list_events(u, after_seq)))


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------
async def _write(ctx, tool: str, key: str, dry_run: bool, args: dict, fn) -> WriteResult:
    if not dry_run and (cached := _idem(f"{tool}:{key}")) is not None:
        return WriteResult(dry_run=False, idempotency_key=key, replayed=True, result=cached)
    res = await _run(ctx, tool, {**args, "idempotency_key": key, "dry_run": dry_run}, fn)
    if not dry_run:
        _idem(f"{tool}:{key}", res)
    return WriteResult(dry_run=dry_run, idempotency_key=key, result=res)


IdemKey = Annotated[str, Field(min_length=8, max_length=128, description="Unique per intended action; "
                                                                          "retries with the same key never repeat it")]


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True,
                                      openWorldHint=True), title="Create proposal draft")
async def create_proposal_draft(
    job_id: Annotated[str, Field(min_length=1, max_length=64)],
    cover_letter: Annotated[str, Field(min_length=50, max_length=5000)],
    bid_amount: Annotated[float, Field(gt=0, le=100000)],
    idempotency_key: IdemKey,
    screening_answers: Annotated[list[Annotated[str, Field(max_length=2000)]], Field(max_length=10)] = [],  # noqa: B006
    ai_assisted: bool | None = None,
    dry_run: bool = False,
    ctx: Context | None = None,
) -> WriteResult:
    """Create a proposal DRAFT (no Connects spent). dry_run=true returns exactly what would be created and the
    Connects it will cost on submit."""
    extra = {"ai_assisted": ai_assisted} if ai_assisted is not None else None
    return await _write(ctx, "create_proposal_draft", idempotency_key, dry_run,
                        {"job_id": job_id, "bid_amount": bid_amount, "cover_letter": cover_letter},
                        lambda u: adapter().create_proposal_draft(u, job_id, cover_letter, bid_amount,
                                                                  screening_answers, idempotency_key, dry_run, extra))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True,
                                      openWorldHint=True), title="Submit proposal")
async def submit_proposal(
    proposal_id: Annotated[str, Field(min_length=1, max_length=64)],
    idempotency_key: IdemKey,
    ai_assisted: bool | None = None,
    dry_run: bool = False,
    ctx: Context | None = None,
) -> WriteResult:
    """Submit an approved proposal draft. SPENDS CONNECTS. Only call after explicit human approval."""
    extra = {"ai_assisted": ai_assisted} if ai_assisted is not None else None
    return await _write(ctx, "submit_proposal", idempotency_key, dry_run, {"proposal_id": proposal_id},
                        lambda u: adapter().submit_proposal(u, proposal_id, idempotency_key, dry_run, extra))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True,
                                      openWorldHint=True), title="Send message")
async def send_message(
    thread_id: Annotated[str, Field(min_length=1, max_length=64)],
    text: Annotated[str, Field(min_length=1, max_length=4000)],
    idempotency_key: IdemKey,
    dry_run: bool = False,
    ctx: Context | None = None,
) -> WriteResult:
    """Send an approved message to a client. Irreversible. Only call after explicit human approval."""
    return await _write(ctx, "send_message", idempotency_key, dry_run, {"thread_id": thread_id, "text": text},
                        lambda u: adapter().send_message(u, thread_id, text, idempotency_key, dry_run))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", default="streamable-http", choices=["streamable-http", "stdio"])
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args()
    mcp.settings.port = a.port
    mcp.run(transport=a.transport)


if __name__ == "__main__":
    main()
