"""Decision + proposal metrics for the full bid graph on the dev set (B4, E5).

Per persona: bid-or-skip F1, scam precision/recall, price inside the fair band,
unsupported claims per proposal (before and after verification), p50/p95
latency, tokens and USD per job analysed and per proposal. With --outcomes the
harness approves every draft and reads GigSim's simulated reply/hire rate.

Run:  GIGBID_LLM_CACHE=1 uv run python -m evals.runners.decision_eval --per-persona 40 --outcomes
"""
from __future__ import annotations

import argparse
import asyncio
import json

from sklearn.metrics import f1_score, precision_score, recall_score

from evals.runners.common import PERSONAS, load_dev, mean, pctl, provenance, write_results
from evals.runners.harness import gather_limited, harness

SEED_TOKENS = {"ai_ml": "gs_ai_ml", "fullstack": "gs_fullstack", "data_analyst": "gs_data_analyst"}


def tot(usage: dict, key: str) -> float:
    return sum(u.get(key, 0) for u in (usage or {}).values())


def price_in_band(price: dict | None, fair: list | None) -> bool | None:
    if not price or not fair:
        return None
    return fair[0] - 1e-6 <= price["amount"] <= fair[1] + 1e-6


async def evaluate(per_persona: int, outcomes: bool, concurrency: int, name: str, policy: int = 1) -> dict:
    records = []
    out_stats = {}
    async with harness(policy) as h:
        for persona in PERSONAS:
            jobs = load_dev(persona, limit=per_persona, seed_every=1)
            results = await gather_limited([h.analyse(persona, j) for j in jobs], concurrency)
            for job, res in zip(jobs, results, strict=True):
                if isinstance(res, Exception):
                    records.append({"persona": persona, "job_id": job["id"], "error": f"{type(res).__name__}: {res}"[:300],
                                    "gold_bid": job["gold"]["bid"], "gold_scam": job["gold"]["scam"]})
                    continue
                dec = res.get("decision") or {}
                ver = res.get("verification") or {}
                usage = res.get("usage") or {}
                pred_bid = dec.get("action") == "bid" and res.get("status") not in ("skipped", "dead_letter")
                records.append({
                    "persona": persona, "job_id": job["id"], "kind": job["gold"]["kind"],
                    "gold_bid": job["gold"]["bid"], "pred_bid": pred_bid, "action": dec.get("action"),
                    "status": res.get("status"), "reasons": dec.get("reasons"),
                    "gold_scam": job["gold"]["scam"], "pred_scam": bool((res.get("risk") or {}).get("is_scam")),
                    "injection": job["gold"]["injection"], "fit": (res.get("fit") or {}).get("fit_score"),
                    "price": res.get("price"), "price_in_band": price_in_band(res.get("price"), job["gold"]["fair_price"]),
                    "drafted": bool(res.get("draft")), "claims": ver.get("claims_total"),
                    "unsupported_before": ver.get("unsupported_before"), "unsupported_after": ver.get("unsupported_after"),
                    "critic_rounds": len(res.get("critiques") or []), "compliance": (res.get("compliance") or {}).get("verdict"),
                    "cover_letter": (res.get("draft") or {}).get("cover_letter"),
                    "tokens": tot(usage, "input_tokens") + tot(usage, "output_tokens"), "usd": round(tot(usage, "usd"), 6),
                    "latency_s": round(res["_wall_s"], 2), "thread_id": res["_thread_id"], "errors": res.get("errors"),
                    "usage_by_node": usage})
            if outcomes:
                drafted = [r for r in records if r["persona"] == persona and r.get("status") == "awaiting_approval"]
                await gather_limited([h.approve(r["thread_id"]) for r in drafted], concurrency)
                o = h.outcomes(SEED_TOKENS[persona])
                out_stats[persona] = {"n_submitted": o["n"], "reply_rate": round(o["reply_rate"], 3),
                                      "hire_rate": round(o["hire_rate"], 3)}
            print(persona, "done", len([r for r in records if r["persona"] == persona]))

    def metrics(rs: list[dict]) -> dict:
        ok = [r for r in rs if "error" not in r and r.get("status") != "dead_letter"]
        yt, yp = [r["gold_bid"] for r in ok], [r["pred_bid"] for r in ok]
        st, sp = [r["gold_scam"] for r in ok], [r["pred_scam"] for r in ok]
        props = [r for r in ok if r["drafted"]]
        jobs_lat = [r["latency_s"] for r in ok]
        prop_lat = [r["latency_s"] for r in props]
        band = [r["price_in_band"] for r in ok if r["price_in_band"] is not None]
        return {
            "n_jobs": len(rs), "n_failed": len(rs) - len(ok), "n_proposals": len(props),
            "bid_f1": round(f1_score(yt, yp, zero_division=0), 3) if ok else None,
            "bid_precision": round(precision_score(yt, yp, zero_division=0), 3) if ok else None,
            "bid_recall": round(recall_score(yt, yp, zero_division=0), 3) if ok else None,
            "scam_precision": round(precision_score(st, sp, zero_division=0), 3) if ok else None,
            "scam_recall": round(recall_score(st, sp, zero_division=0), 3) if ok else None,
            "price_in_fair_band": round(sum(band) / len(band), 3) if band else None,
            "unsupported_claims_per_proposal_before": mean(r["unsupported_before"] for r in props),
            "unsupported_claims_per_proposal_after": mean(r["unsupported_after"] for r in props),
            "claims_per_proposal": mean(r["claims"] for r in props),
            "critic_rounds_mean": mean(r["critic_rounds"] for r in props),
            "latency_per_job_p50_s": pctl(jobs_lat, .5), "latency_per_job_p95_s": pctl(jobs_lat, .95),
            "latency_per_proposal_p50_s": pctl(prop_lat, .5), "latency_per_proposal_p95_s": pctl(prop_lat, .95),
            "tokens_per_job": mean(r["tokens"] for r in ok), "tokens_per_proposal": mean(r["tokens"] for r in props),
            "usd_per_job": mean(r["usd"] for r in ok), "usd_per_proposal": mean(r["usd"] for r in props),
        }

    summary = {"overall": metrics(records), "by_persona": {p: metrics([r for r in records if r["persona"] == p])
                                                           for p in PERSONAS}}
    if outcomes:
        n = sum(v["n_submitted"] for v in out_stats.values()) or 1
        summary["gigsim_outcomes"] = {**out_stats, "overall": {
            "n_submitted": n, "reply_rate": round(sum(v["reply_rate"] * v["n_submitted"] for v in out_stats.values()) / n, 3),
            "hire_rate": round(sum(v["hire_rate"] * v["n_submitted"] for v in out_stats.values()) / n, 3)}}
    return {"provenance": provenance({"per_persona": per_persona, "policy_version": policy}), "summary": summary,
            "records": records}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-persona", type=int, default=40)
    ap.add_argument("--outcomes", action="store_true")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--policy", type=int, default=1)
    ap.add_argument("--name", default="decision_eval")
    a = ap.parse_args()
    out = asyncio.run(evaluate(a.per_persona, a.outcomes, a.concurrency, a.name, a.policy))
    p = write_results(a.name, out)
    print(json.dumps(out["summary"], indent=1))
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
