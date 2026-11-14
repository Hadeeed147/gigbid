"""The single marketplace interface (R1).

Two adapters implement it, switched by config `marketplace.mode`:
  - mcp_servers/marketplace/adapters/gigsim.py      (GigSim REST)
  - mcp_servers/marketplace/adapters/upwork_live.py (official Upwork MCP server, OAuth 2.1)

The Marketplace MCP server exposes this port as tools; agents only ever see the
tools, so the graph cannot tell which marketplace it is talking to.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class MarketplaceUnavailable(RuntimeError):
    """Raised after bounded retries when the marketplace cannot be reached (degraded mode)."""


class MarketplaceRejected(RuntimeError):
    """The marketplace refused the request (validation, policy, insufficient Connects)."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


class Budget(BaseModel):
    type: str = Field(description="hourly | fixed")
    min: float | None = None
    max: float | None = None
    amount: float | None = None
    estimated_hours: float | None = None


class Job(BaseModel):
    id: str
    title: str
    description: str
    category: str | None = None
    budget: Budget | None = None
    client_id: str | None = None
    screening_questions: list[str] = []
    connects_cost: int | None = None
    posted_at: str | None = None
    source: str | None = None


class ClientHistory(BaseModel):
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


@runtime_checkable
class MarketplacePort(Protocol):
    name: str

    # read
    def search_jobs(self, user: str, query: str = "", category: str = "", posted_after: str = "",
                    limit: int = 20) -> list[Job]: ...
    def get_job(self, user: str, job_id: str) -> Job: ...
    def get_client_history(self, user: str, client_id: str) -> ClientHistory: ...
    def get_connects_balance(self, user: str) -> int: ...
    def get_policy(self, user: str) -> dict[str, Any]: ...
    def list_threads(self, user: str) -> list[dict]: ...
    def list_messages(self, user: str, thread_id: str) -> list[dict]: ...
    def list_events(self, user: str, after_seq: int = 0) -> list[dict]: ...

    # write (every call carries an idempotency key; dry_run returns the exact preview + cost)
    def create_proposal_draft(self, user: str, job_id: str, cover_letter: str, bid_amount: float,
                              screening_answers: list[str], idempotency_key: str, dry_run: bool,
                              extra: dict | None = None) -> dict: ...
    def submit_proposal(self, user: str, proposal_id: str, idempotency_key: str, dry_run: bool,
                        extra: dict | None = None) -> dict: ...
    def send_message(self, user: str, thread_id: str, text: str, idempotency_key: str,
                     dry_run: bool) -> dict: ...


def get_adapter(mode: str | None = None) -> MarketplacePort:
    from common.config import cfg
    mode = mode or cfg("marketplace.mode", "gigsim")
    if mode == "gigsim":
        from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
        return GigSimAdapter()
    if mode == "upwork_live":
        from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter
        return UpworkLiveAdapter()
    raise ValueError(f"unknown marketplace mode {mode}")
