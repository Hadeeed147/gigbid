"""Risk Assessor: client quality from history + scam / free-work / off-platform /
injection flags. Rule signals are combined with the LLM so one cannot be talked
out of a hard signal by the other."""
from __future__ import annotations

import json
import re

from agent.handoffs import RiskReport
from agent.mcp_client import get_hub
from agent.nodes._runtime import detect_injection, job_text, node, untrusted
from common.llm import chat
from common.prompts import load_prompt

RULES = {
    "off_platform_contact": r"(?i)\b(whatsapp|telegram|skype|wechat|signal app|personal email|gmail\.com)\b|\+\d[\d\s-]{8,}",
    "off_platform_payment": r"(?i)\b(paypal|crypto|bitcoin|usdt|wallet address|outside the platform|cheque|wire transfer)\b",
    "free_work": r"(?i)\b(free|unpaid) (test|sample|trial)\b|test task.{0,40}(best one|free)",
    "pay_to_work": r"(?i)\b(buy|purchase|pay for) (our|the|a) (training|kit|starter|software)\b",
}


def rule_signals(job: dict, client: dict) -> tuple[list[str], float]:
    text = job.get("description", "") + " " + job.get("title", "")
    flags = [k for k, p in RULES.items() if re.search(p, text)]
    if detect_injection(text):
        flags.append("prompt_injection")
    score = 0.0
    if client:
        if client.get("payment_verified") is False:
            flags.append("unverified_payment")
            score += 0.25
        if not client.get("hires"):
            flags.append("no_history")
            score += 0.15
    hard = {"off_platform_contact", "off_platform_payment", "free_work", "pay_to_work"} & set(flags)
    score += 0.45 * min(2, len(hard))
    return flags, min(1.0, score)


@node("risk")
async def risk(state: dict) -> dict:
    job = state["job"]
    hub = await get_hub()
    client = {}
    if job.get("client_id"):
        client = await hub.call("risk", "get_client_history", {"client_id": job["client_id"]})
    flags, rule_score = rule_signals(job, client)
    sys = load_prompt("risk", untrusted=load_prompt("_untrusted"))
    hist = json.dumps({k: client.get(k) for k in ("payment_verified", "total_spent", "hires", "jobs_posted",
                                                  "avg_rating_given", "member_since", "reviews_from_freelancers")})
    rep = chat("risk", [{"role": "system", "content": sys},
                        {"role": "user", "content": untrusted("job_post", job_text(job, sanitize=False)) + "\n\n" +
                         untrusted("client_history", hist) + f"\n\nRule-based flags already found: {flags}"}],
               RiskReport)
    rep.flags = sorted(set(rep.flags) | set(flags))
    rep.injection_detected = rep.injection_detected or "prompt_injection" in flags
    rep.risk_score = round(max(rep.risk_score, rule_score), 3)
    hard = {"off_platform_contact", "off_platform_payment", "free_work", "pay_to_work"} & set(rep.flags)
    rep.is_scam = rep.is_scam or (len(hard) >= 1 and rule_score >= 0.45)
    return {"risk": rep.model_dump(), "client": client}
