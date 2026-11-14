"""Pricing Strategist: bid from market statistics, client spend and the user's
floor; decides whether the Connects cost is worth it.

Default mode "rules" is a transparent formula (auditable, zero tokens); "llm"
asks the model and clamps its answer to the same hard bounds."""
from __future__ import annotations

from agent.handoffs import PriceQuote
from agent.mcp_client import get_hub
from agent.nodes._runtime import node
from common.config import cfg
from common.llm import chat
from common.prompts import load_prompt


def quote(job: dict, profile: dict, stats: dict, client: dict, fit: float, risk: float, connects: int,
          balance: int) -> PriceQuote:
    b = job.get("budget") or {}
    floor = float(profile.get("rate_floor", 0))
    rate = float(profile.get("hourly_rate", floor or stats["hourly_p50"]))
    spend_bonus = 0.05 if (client.get("total_spent") or 0) > 10000 else 0.0
    if b.get("type") == "hourly":
        lo, hi = float(b.get("min") or stats["hourly_p25"]), float(b.get("max") or stats["hourly_p75"])
        target = lo + (hi - lo) * min(1.0, 0.35 + 0.6 * fit + spend_bonus)
        target = max(floor, min(hi, max(target, min(rate, hi))))
        band = (max(floor, lo), hi)
        unit, amount = "hourly", round(target, 0)
        why = (f"client range ${lo:.0f}-{hi:.0f}/h, market median ${stats['hourly_p50']:.0f}/h, your floor ${floor:.0f}/h,"
               f" fit {fit:.2f} -> ${amount:.0f}/h")
    else:
        amt = float(b.get("amount") or 0)
        factor = 0.9 + 0.2 * fit + spend_bonus
        amount = round(min(amt * 1.1, max(amt * 0.8, amt * factor)), -1) if amt else round(rate * 20, -1)
        band = (round(amt * 0.8), round(amt * 1.1)) if amt else (amount * 0.9, amount * 1.1)
        unit = "fixed"
        why = f"fixed budget ${amt:.0f}, fit {fit:.2f} -> ${amount:.0f} (within 80-110% of budget)"
    value = fit * (1 - risk)
    worth = connects <= balance and value >= 0.35
    why += f"; Connects {connects} of {balance} available, value score {value:.2f} -> {'worth it' if worth else 'not worth it'}"
    return PriceQuote(amount=amount, unit=unit, band=band, connects_cost=connects, connects_worth_it=worth,
                      rationale=why)


@node("pricing")
async def pricing(state: dict) -> dict:
    job, profile = state["job"], state.get("profile", {})
    hub = await get_hub()
    stats = await hub.call("pricing", "get_market_stats", {"category": job.get("category") or ""})
    balance = (await hub.call("pricing", "get_connects_balance", {}))["balance"]
    fit = state.get("fit", {}).get("fit_score", 0.0)
    risk = state.get("risk", {}).get("risk_score", 0.0)
    q = quote(job, profile, stats, state.get("client", {}), fit, risk, int(job.get("connects_cost") or 0), balance)
    if cfg("pricing.mode") == "llm":
        llm_q = chat("pricing", [{"role": "system", "content": load_prompt("pricing")},
                                 {"role": "user", "content": f"Rules-based quote: {q.model_dump_json()}\nStats: {stats}"}],
                     PriceQuote)
        q.amount = max(q.band[0], min(q.band[1], llm_q.amount))
        q.rationale = llm_q.rationale + " (clamped to hard bounds)"
    out = {"price": q.model_dump()}
    if not q.connects_worth_it and not state.get("force_bid"):
        out["decision"] = {"action": "skip", "reasons": ["Connects cost not worth it: " + q.rationale], "auto": False}
        out["status"] = "skipped"
    return out
