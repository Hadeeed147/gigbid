"""Bid graph: one thread per job (C1).

intake --Send--> analyst | risk | matcher  (parallel)  --> decide
decide --bid--> pricing --> writer --> verifier --> critic --(<=2 revisions)--> writer
critic --> compliance --(block)--> END
compliance --> preview (dry_run) --> approval [interrupt]
approval --edit--> compliance (re-check) ; --reject--> END ; --approve--> submit --> END
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agent.nodes._runtime import TERMINAL
from agent.nodes.analyst import analyst
from agent.nodes.approval import approval, preview, submit
from agent.nodes.compliance import compliance
from agent.nodes.critic import critic
from agent.nodes.decision import decide
from agent.nodes.matcher import matcher
from agent.nodes.pricing import pricing
from agent.nodes.risk import risk
from agent.nodes.scout import intake
from agent.nodes.verifier import verifier
from agent.nodes.writer import writer
from agent.state import BidState


def _stop(state: dict) -> bool:
    return state.get("status") in TERMINAL


def fan_out(state: dict):
    if _stop(state):
        return END
    return [Send("analyst", state), Send("risk", state), Send("matcher", state)]


def after_decide(state: dict) -> str:
    return END if _stop(state) or state.get("decision", {}).get("action") != "bid" else "pricing"


def after_critic(state: dict) -> str:
    if _stop(state):
        return END
    crit = (state.get("critiques") or [{}])[-1]
    if not crit.get("approved") and state.get("revision", 0) > crit.get("revision", 0):
        return "writer"          # send back with reasons (bounded by loops.max_critic_revisions)
    return "compliance"


def after_approval(state: dict) -> str:
    s = state.get("status")
    if s == "recheck":
        return "compliance"      # edits are re-checked by Compliance before re-approval
    if s == "approved":
        return "submit"
    return END


def nxt(target: str):
    return lambda state: END if _stop(state) else target


def build_bid_graph(checkpointer=None, store=None):
    g = StateGraph(BidState)
    for fn in (intake, analyst, risk, matcher, decide, pricing, writer, verifier, critic, compliance, preview,
               approval, submit):
        g.add_node(fn.node_name, fn)
    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", fan_out, ["analyst", "risk", "matcher", END])
    for n in ("analyst", "risk", "matcher"):
        g.add_edge(n, "decide")
    g.add_conditional_edges("decide", after_decide, ["pricing", END])
    g.add_conditional_edges("pricing", nxt("writer"), ["writer", END])
    g.add_conditional_edges("writer", nxt("verifier"), ["verifier", END])
    g.add_conditional_edges("verifier", nxt("critic"), ["critic", END])
    g.add_conditional_edges("critic", after_critic, ["writer", "compliance", END])
    g.add_conditional_edges("compliance", nxt("preview"), ["preview", END])
    g.add_conditional_edges("preview", nxt("approval"), ["approval", END])
    g.add_conditional_edges("approval", after_approval, ["compliance", "submit", END])
    g.add_edge("submit", END)
    return g.compile(checkpointer=checkpointer, store=store)
