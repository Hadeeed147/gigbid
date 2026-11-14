"""Client Liaison (conversation graph): read new messages, classify intent,
draft a reply or interview slots, then wait for approval before sending."""
from __future__ import annotations

import hashlib

from langgraph.types import interrupt

from agent.handoffs import ApprovalDecision, Intent, ReplyDraft
from agent.mcp_client import get_hub
from agent.memory.store import style_rules
from agent.nodes._runtime import detect_injection, node, untrusted
from agent.nodes.compliance import check_text
from agent.nodes.risk import RULES
from common.llm import chat
from common.prompts import load_prompt

import re


@node("load_thread")
async def load_thread(state: dict) -> dict:
    hub = await get_hub()
    msgs = (await hub.call("liaison", "list_messages", {"thread_id": state["thread_id"]}))["items"]
    return {"messages": msgs, "status": "classifying"}


@node("intent")
async def intent(state: dict) -> dict:
    last = next((m for m in reversed(state["messages"]) if m["sender"] == "client"), None)
    if not last:
        return {"intent": {"intent": "other", "confidence": 1.0, "reason": "no client message"}, "status": "watch"}
    text = last["text"]
    rule_scam = any(re.search(RULES[k], text) for k in ("off_platform_contact", "off_platform_payment", "free_work")) \
        or bool(detect_injection(text))
    it = chat("intent", [{"role": "system", "content": load_prompt("intent", untrusted=load_prompt("_untrusted"))},
                         {"role": "user", "content": untrusted("client_message", text)}], Intent)
    if rule_scam and it.intent != "scam_signal":
        it = Intent(intent="scam_signal", confidence=max(it.confidence, 0.8), reason="rule: off-platform/injection signal")
    return {"intent": it.model_dump(), "status": "drafting"}


@node("slots")
async def slots(state: dict) -> dict:
    if state["intent"]["intent"] != "interview_request":
        return {"slots": []}
    hub = await get_hub()
    res = await hub.call("liaison", "free_slots", {"days_ahead": 5, "duration_minutes": 30, "max_slots": 3})
    return {"slots": res["slots"]}


@node("draft_reply")
async def draft_reply(state: dict) -> dict:
    profile = state.get("profile", {})
    rules = style_rules(state.get("user_id", ""))
    sys = load_prompt("liaison", untrusted=load_prompt("_untrusted"), freelancer_name=profile.get("name", "the freelancer"),
                      rate_floor=f"${profile.get('rate_floor', 0)}/h",
                      style_rules=("Style rules learned from the user's edits:\n- " + "\n- ".join(rules)) if rules else "")
    convo = "\n".join(f"{m['sender']}: {m['text']}" for m in state["messages"][-8:])
    slot_txt = "\n".join(f"- {s['start']} ({s['timezone']})" for s in state.get("slots", [])) or "(none)"
    user = (untrusted("client_message", convo) + f"\n\nIntent: {state['intent']}\nFree interview slots:\n{slot_txt}"
            f"\nJob: {state.get('job', {}).get('title', '')}")
    r = chat("liaison", [{"role": "system", "content": sys}, {"role": "user", "content": user}], ReplyDraft)
    r.proposed_slots = state.get("slots", [])
    v = check_text(r.text)
    if v.verdict == "block":
        return {"reply": r.model_dump(), "compliance": v.model_dump(), "status": "blocked",
                "attention_reason": "Compliance Guard blocked the reply"}
    r.text = v.cleaned_text or r.text
    return {"reply": r.model_dump(), "compliance": v.model_dump(), "status": "awaiting_approval"}


@node("approve_reply")
async def approve_reply(state: dict) -> dict:
    d = ApprovalDecision(**interrupt({"type": "message_approval", "thread_id": state["thread_id"],
                                      "messages": state["messages"][-6:], "intent": state["intent"],
                                      "reply": state["reply"], "compliance": state.get("compliance", {}),
                                      "slots": state.get("slots", [])}))
    rec = d.model_dump()
    if d.action == "reject":
        return {"approvals": [rec], "status": "rejected", "attention_reason": f"rejected: {d.reason}"}
    reply = dict(state["reply"])
    if d.action == "edit" and d.text:
        from agent.memory.store import record_edit
        record_edit(state.get("user_id", ""), reply["text"], d.text)
        reply["text"] = check_text(d.text, use_llm=False).cleaned_text or d.text
    reply["chosen_slot"] = d.slot_start
    return {"approvals": [rec], "reply": reply, "status": "approved"}


@node("send")
async def send(state: dict) -> dict:
    hub = await get_hub()
    text = state["reply"]["text"]
    key = f"{state['thread_id']}:msg:{hashlib.sha256(text.encode()).hexdigest()[:12]}"
    res = await hub.call("send", "send_message", {"thread_id": state["thread_id"], "text": text, "idempotency_key": key})
    hold = None
    if state["reply"].get("chosen_slot"):
        hold = await hub.call("send", "create_interview_hold", {"start": state["reply"]["chosen_slot"],
                                                                "idempotency_key": key + ":hold"})
    return {"sent": {**res["result"], "hold": hold}, "status": "sent"}
