"""Node runtime: budgets, retries, timeouts, degraded mode, dead-letter, usage + trace.

Every graph node is wrapped with @node(name). The wrapper:
  * skips work once the thread is in a terminal state;
  * enforces the per-thread step and token budgets (-> "needs_attention");
  * retries transient failures with backoff and a per-node timeout;
  * re-raises MarketplaceUnavailable as DegradedError so LangGraph does NOT
    commit the node; the checkpoint stays at the last good step and the worker
    resumes the same thread later (queue + recover);
  * turns any other persistent failure into a "dead_letter" status;
  * records tokens/cost per node and appends to the execution trace.
"""
from __future__ import annotations

import asyncio
import functools
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from agent.marketplace_port import MarketplaceUnavailable
from agent.mcp_client import exec_trace, run_identity
from common.config import cfg
from common.llm import LLMError, Usage, current_usage

TERMINAL = {"dead_letter", "needs_attention", "skipped", "watch", "blocked", "rejected", "submitted", "sent"}


class DegradedError(RuntimeError):
    """Marketplace unavailable: leave the thread resumable from this node."""


def tokens_used(state: dict) -> int:
    return sum(u.get("input_tokens", 0) + u.get("output_tokens", 0) for u in (state.get("usage") or {}).values())


def node(name: str, *, allow_terminal: bool = False):
    def deco(fn: Callable[[dict], Awaitable[dict]]):
        @functools.wraps(fn)
        async def wrapper(state: dict) -> dict:
            if not allow_terminal and state.get("status") in TERMINAL:
                return {}
            step_budget = cfg("loops.thread_step_budget", 40)
            token_budget = cfg("loops.thread_token_budget", 60000)
            if state.get("steps", 0) >= step_budget:
                return {"status": "needs_attention", "attention_reason": f"step budget ({step_budget}) exceeded at {name}"}
            if tokens_used(state) >= token_budget:
                return {"status": "needs_attention",
                        "attention_reason": f"token budget ({token_budget}) exceeded at {name}"}
            usage, tr = Usage(), []
            u_tok, t_tok = current_usage.set(usage), exec_trace.set(tr)
            id_tok = run_identity.set((state.get("user_id") or state.get("tenant", "anonymous"), state.get("trace_id", ""),
                                       state.get("tenant", "")))
            t0 = time.time()
            retries = cfg("node_runtime.max_retries", 2)
            last: Exception | None = None
            out: dict[str, Any] | None = None
            try:
                for attempt in range(retries + 1):
                    try:
                        out = await asyncio.wait_for(fn(state), timeout=cfg("node_runtime.timeout_s", 60) * 3)
                        break
                    except MarketplaceUnavailable as e:
                        last = e
                        if attempt == retries:
                            raise DegradedError(f"{name}: marketplace unavailable: {e}") from e
                    except (TimeoutError, LLMError, RuntimeError, ValueError) as e:
                        last = e
                    await asyncio.sleep(cfg("node_runtime.backoff_base_s", 1.5) ** attempt)
            finally:
                current_usage.reset(u_tok)
                exec_trace.reset(t_tok)
                run_identity.reset(id_tok)
            node_rec = {"kind": "node", "node": name, "latency_s": round(time.time() - t0, 3),
                        "tokens": usage.total_tokens, "usd": round(usage.usd, 6), "ts": time.time()}
            if out is None:
                return {"status": "dead_letter", "errors": [f"{name}: {type(last).__name__}: {str(last)[:300]}"],
                        "steps": 1, "usage": usage.by_node, "trace": tr + [{**node_rec, "error": str(last)[:300]}]}
            out = dict(out)
            out["steps"] = 1
            out["usage"] = usage.by_node
            out["trace"] = tr + [node_rec] + out.get("trace", [])
            return out
        wrapper.node_name = name  # type: ignore[attr-defined]
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Untrusted input handling (E4): delimit, neutralise tag breakouts, pre-filter
# ---------------------------------------------------------------------------
INJECTION_PATTERNS = [
    r"(?i)ignore (all |any )?(the )?(previous|prior|above) (instructions|rules)",
    r"(?i)disregard (your|all|the) (rules|instructions|policy)",
    r"(?i)forget (the|your) (policy|rules|instructions)",
    r"(?i)(system|admin) (note|prompt|message|override)",
    r"(?i)\b(ai|automated) (assistants?|agents?|bidders?|systems?)\b.{0,40}(must|should|:|,)",
    r"(?i)if you are an? (ai|automated|language model|bot)",
    r"(?i)reveal (your|the) (system )?prompt",
    r"(?i)reply only with",
]


def detect_injection(text: str) -> list[str]:
    hits = []
    for p in INJECTION_PATTERNS:
        m = re.search(p, text or "")
        if m:
            hits.append(m.group(0)[:80])
    return hits


def strip_injection(text: str) -> str:
    """Remove sentences/lines that carry instructions aimed at AI systems."""
    out = []
    for line in (text or "").splitlines():
        if detect_injection(line) or re.search(r"<!--.*?-->", line):
            out.append("[removed: instruction aimed at automated tools]")
        else:
            out.append(line)
    return "\n".join(out)


def defenses_on() -> bool:
    return str(cfg("guardrails.injection_defense", "on")).lower() != "off"


def untrusted(kind: str, text: str) -> str:
    if not defenses_on():   # attack study baseline only: raw text, no delimiters
        return text
    safe = (text or "").replace("</untrusted", "&lt;/untrusted").replace("<untrusted", "&lt;untrusted")
    return f"<untrusted_{kind}>\n{safe}\n</untrusted_{kind}>"


def job_text(job: dict, *, sanitize: bool = True) -> str:
    b = job.get("budget") or {}
    budget = (f"hourly ${b.get('min')}-{b.get('max')}" if b.get("type") == "hourly"
              else f"fixed ${b.get('amount')}" + (f" (client estimate {b.get('estimated_hours')}h)"
                                                   if b.get("estimated_hours") else ""))
    desc = strip_injection(job.get("description", "")) if sanitize and defenses_on() else job.get("description", "")
    qs = "\n".join(f"Q{i + 1}: {q}" for i, q in enumerate(job.get("screening_questions") or []))
    return f"Title: {job.get('title', '')}\nCategory: {job.get('category', '')}\nBudget: {budget}\n\n{desc}" + \
        (f"\n\nScreening questions:\n{qs}" if qs else "")
