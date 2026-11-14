"""Conversation graph: one thread per client conversation (C1).

load_thread --> intent (question | negotiation | interview_request | scam_signal)
           --> slots (interview requests only) --> draft_reply (+ compliance)
           --> approve_reply [interrupt] --approve/edit--> send ; --reject--> END
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent.nodes._runtime import TERMINAL
from agent.nodes.liaison import approve_reply, draft_reply, intent, load_thread, send, slots
from agent.state import ConvState


def nxt(target: str):
    return lambda s: END if s.get("status") in TERMINAL else target


def build_conversation_graph(checkpointer=None, store=None):
    g = StateGraph(ConvState)
    for fn in (load_thread, intent, slots, draft_reply, approve_reply, send):
        g.add_node(fn.node_name, fn)
    g.add_edge(START, "load_thread")
    g.add_conditional_edges("load_thread", nxt("intent"), ["intent", END])
    g.add_conditional_edges("intent", nxt("slots"), ["slots", END])
    g.add_conditional_edges("slots", nxt("draft_reply"), ["draft_reply", END])
    g.add_conditional_edges("draft_reply", nxt("approve_reply"), ["approve_reply", END])
    g.add_conditional_edges("approve_reply", lambda s: "send" if s.get("status") == "approved" else END,
                            ["send", END])
    g.add_edge("send", END)
    return g.compile(checkpointer=checkpointer, store=store)
