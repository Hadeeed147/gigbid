"""Decision node: skip, watch or bid, from config thresholds (never hard-coded)."""
from __future__ import annotations

from agent.handoffs import BidDecision
from agent.nodes._runtime import node
from common.config import cfg


def underpriced(job: dict, floor: float) -> bool:
    b = job.get("budget") or {}
    if b.get("type") == "hourly":
        return (b.get("max") or 0) < floor
    if b.get("amount") and b.get("estimated_hours"):
        return b["amount"] / b["estimated_hours"] < floor * 0.7
    return False


def decide_rules(state: dict) -> BidDecision:
    risk, fit, job = state.get("risk", {}), state.get("fit", {}), state.get("job", {})
    profile = state.get("profile", {})
    floor = profile.get("rate_floor", 0)
    reasons = []
    fit_score = fit.get("fit_score", 0.0)
    if job.get("_duplicate"):
        return BidDecision(action="skip", reasons=["duplicate of a job already analysed"])
    if risk.get("is_scam") or risk.get("risk_score", 0) >= cfg("decision.scam_risk_threshold", 0.7):
        return BidDecision(action="skip", reasons=[f"scam/high risk: {', '.join(risk.get('flags', [])) or 'risk score'}"])
    if risk.get("risk_score", 0) > cfg("decision.max_risk_to_bid", 0.6):
        reasons.append(f"risk {risk.get('risk_score')} above bid threshold")
    if underpriced(job, floor):
        return BidDecision(action="skip", reasons=[f"budget below the rate floor (${floor}/h)"])
    if state.get("force_bid"):
        return BidDecision(action="bid", reasons=["user chose to bid anyway"] + reasons)
    if fit_score >= cfg("decision.bid_min_fit", 0.55) and not reasons:
        return BidDecision(action="bid", reasons=[f"fit {fit_score:.2f} >= {cfg('decision.bid_min_fit')}"])
    if fit_score >= cfg("decision.watch_min_fit", 0.4):
        return BidDecision(action="watch", reasons=[f"fit {fit_score:.2f} is borderline"] + reasons)
    auto = profile.get("autonomy") == "auto_skip_low_fit" and fit_score < cfg("decision.auto_skip_below_fit", 0.25)
    return BidDecision(action="skip", reasons=[f"fit {fit_score:.2f} too low"] + reasons, auto=auto)


@node("decide")
async def decide(state: dict) -> dict:
    d = decide_rules(state)
    status = {"bid": "pricing", "watch": "watch", "skip": "skipped"}[d.action]
    return {"decision": d.model_dump(), "status": status}
