"""Typed graph state with reducers (C2).

Three things are kept apart:
  * State (this module): what one job / conversation needs right now.
  * Execution trace (`trace` field + LangSmith): every tool call, argument,
    result and observation, append-only, for audit and debugging. It is never
    read back by agents to make decisions.
  * Long-term memory (agent/memory): only promoted knowledge, in a LangGraph
    store, written by explicit promotion rules. Raw tool output never goes there.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_dicts(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


def merge_usage(a: dict | None, b: dict | None) -> dict:
    """Sum per-node token/cost usage written by parallel branches."""
    out = {k: dict(v) for k, v in (a or {}).items()}
    for node, u in (b or {}).items():
        cur = out.setdefault(node, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0, "latency_s": 0.0})
        for k in ("calls", "input_tokens", "output_tokens", "usd", "latency_s"):
            cur[k] = cur.get(k, 0) + u.get(k, 0)
        if "model" in u:
            cur["model"] = u["model"]
    return out


def last_status(a: str | None, b: str | None) -> str | None:
    """Terminal statuses win over progress statuses when branches race."""
    terminal = ("dead_letter", "needs_attention", "degraded")
    if a in terminal and b not in terminal:
        return a
    return b if b is not None else a


class BidState(TypedDict, total=False):
    # identity
    user_id: str
    tenant: str                     # portfolio tenant (persona or user id)
    job_id: str
    thread_id: str
    trace_id: str
    profile: dict                   # rate floor, usual rate, name, autonomy (from user settings)
    force_bid: bool                 # user overrode a skip from the UI

    # the job (untrusted text lives here; it is always delimited before reaching a prompt)
    job: dict[str, Any]
    client: dict[str, Any]

    # analyses: written by the three parallel branches into separate keys
    job_spec: dict
    risk: dict
    fit: dict
    evidence: Annotated[dict, merge_dicts]          # requirement -> evidence items
    exemplars: list[dict]

    # decisions and drafts
    decision: dict
    price: dict
    draft: dict
    verification: dict
    critiques: Annotated[list[dict], operator.add]
    revision: int
    compliance: dict
    preview: dict                                    # dry_run preview shown on the approval screen
    approvals: Annotated[list[dict], operator.add]   # every approval decision (approve / edit / reject)
    submission: dict
    outcome: dict

    # control
    status: Annotated[str | None, last_status]
    attention_reason: str | None
    errors: Annotated[list[str], operator.add]
    steps: Annotated[int, operator.add]
    usage: Annotated[dict, merge_usage]
    trace: Annotated[list[dict], operator.add]       # execution trace (audit only)


class ConvState(TypedDict, total=False):
    user_id: str
    tenant: str
    thread_id: str
    trace_id: str
    profile: dict
    job: dict
    messages: list[dict]
    intent: dict
    slots: list[dict]
    reply: dict
    compliance: dict
    approvals: Annotated[list[dict], operator.add]
    sent: dict
    status: Annotated[str | None, last_status]
    attention_reason: str | None
    errors: Annotated[list[str], operator.add]
    steps: Annotated[int, operator.add]
    usage: Annotated[dict, merge_usage]
    trace: Annotated[list[dict], operator.add]
