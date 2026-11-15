"""Signature extension X2: proposal strategy A/B test in GigSim with a significance test.

Paired design: every bid-worthy dev job is drafted with strategy A (evidence-first,
shipped) AND strategy B (question-first, short), by the same pipeline. Each version
is submitted from its own GigSim account, so the same simulated client judges both.
Reply outcomes are therefore paired per job:
  * McNemar's exact test on the discordant pairs (the right test for paired binary outcomes)
  * a two-proportion z-test reported alongside for readers used to unpaired A/B tests
  * the minimum detectable effect at this n, so a non-significant result is read correctly

Run:  GIGBID_LLM_CACHE=1 uv run python -m evals.runners.ab_test --per-persona 20
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os

from scipy.stats import binomtest, norm

from common.config import reload_config
from evals.runners.common import PERSONAS, load_dev, provenance, public, write_results

A = {"X-Admin-Key": "gigsim-admin"}


def two_prop_z(x1: int, n1: int, x2: int, n2: int) -> float:
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) or 1e-9
    return 2 * (1 - norm.cdf(abs(x1 / n1 - x2 / n2) / se))


def mde(p: float, n: int, alpha: float = 0.05, power: float = 0.8) -> float:
    """Approximate minimum detectable absolute difference for two proportions with n per arm."""
    return (norm.ppf(1 - alpha / 2) + norm.ppf(power)) * math.sqrt(2 * p * (1 - p) / max(n, 1))


async def draft_all(strategy: str, jobs) -> dict[str, str]:
    os.environ["GIGBID_PROPOSAL_STRATEGY"] = strategy
    reload_config()
    from agent.nodes.writer import strip_citations
    from agent.runtime import config_for, initial_bid_state, persona_profile
    from evals.runners.harness import gather_limited, harness
    texts = {}
    async with harness() as h:
        async def one(persona, job):
            st = initial_bid_state(f"ab-{strategy}", persona, public(job), persona_profile(persona), force_bid=True)
            out = await h.graph.ainvoke(st, config_for(st["thread_id"]))
            return job["id"], (out.get("draft") or {}).get("cover_letter"), (out.get("price") or {}).get("amount")
        for r in await gather_limited([one(p, j) for p, j in jobs], 3):
            if not isinstance(r, Exception) and r[1]:
                texts[r[0]] = (strip_citations(r[1]), r[2])
    return texts


def submit_and_score(jobs, drafts: dict[str, dict]) -> list[dict]:
    """Submit both versions into ONE fresh GigSim from separate accounts and read the client decisions."""
    from fastapi.testclient import TestClient

    from evals.runners.harness import gigsim
    import tempfile
    from pathlib import Path
    gigsim.DB_PATH = Path(tempfile.mkdtemp()) / "ab.sqlite"
    gigsim.init_db(reset=True)
    gigsim.RATE_LIMIT = 10_000
    tc = TestClient(gigsim.app)
    tc.post("/admin/clock", json={"advance_minutes": 60 * 24 * 8}, headers=A)
    for arm in ("A", "B"):
        tc.post("/admin/accounts", json={"token": f"ab_{arm}", "name": f"arm {arm}", "connects": 100000}, headers=A)
    rows = []
    for persona, job in jobs:
        pair = {}
        for arm in ("A", "B"):
            d = drafts[arm].get(job["id"])
            if not d or len(d[0]) < 50:
                break
            H = {"Authorization": f"Bearer ab_{arm}"}
            b = job["budget"]
            p = tc.post("/proposals", json={"job_id": job["id"], "cover_letter": d[0][:5000],
                                            "bid_amount": float(d[1] or b.get("max") or b.get("amount") or 1)}, headers=H).json()
            tc.post(f"/proposals/{p['id']}/submit", json={}, headers=H)
            pair[arm] = p["id"]
        if len(pair) < 2:
            continue
        outs = {o["id"]: o["decision"] for o in tc.get("/admin/outcomes", headers=A).json()["proposals"]}
        rows.append({"persona": persona, "job_id": job["id"], "A_replied": outs[pair["A"]]["replied"],
                     "B_replied": outs[pair["B"]]["replied"], "A_score": outs[pair["A"]]["score"],
                     "B_score": outs[pair["B"]]["score"], "A_words": len(drafts["A"][job["id"]][0].split()),
                     "B_words": len(drafts["B"][job["id"]][0].split())})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-persona", type=int, default=20)
    a = ap.parse_args()
    jobs = [(p, j) for p in PERSONAS for j in load_dev(p) if j["gold"]["bid"]][:]
    jobs = [x for i, x in enumerate(jobs) if sum(1 for y in jobs[:i] if y[0] == x[0]) < a.per_persona]
    drafts = {arm: asyncio.run(draft_all(arm, jobs)) for arm in ("A", "B")}
    os.environ["GIGBID_PROPOSAL_STRATEGY"] = "A"
    reload_config()
    rows = submit_and_score(jobs, drafts)
    n = len(rows)
    xa, xb = sum(r["A_replied"] for r in rows), sum(r["B_replied"] for r in rows)
    b_only = sum(1 for r in rows if r["B_replied"] and not r["A_replied"])
    a_only = sum(1 for r in rows if r["A_replied"] and not r["B_replied"])
    mcnemar_p = binomtest(min(a_only, b_only), a_only + b_only, 0.5).pvalue if (a_only + b_only) else 1.0
    pooled = (xa + xb) / (2 * n) if n else 0
    summary = {"n_pairs": n, "reply_rate_A": round(xa / n, 3) if n else None, "reply_rate_B": round(xb / n, 3) if n else None,
               "discordant_A_only": a_only, "discordant_B_only": b_only, "mcnemar_exact_p": round(mcnemar_p, 4),
               "two_proportion_z_p": round(two_prop_z(xa, n, xb, n), 4) if n else None,
               "min_detectable_diff_at_80pct_power": round(mde(pooled, n), 3) if n else None,
               "mean_client_score_A": round(sum(r["A_score"] for r in rows) / n, 3) if n else None,
               "mean_client_score_B": round(sum(r["B_score"] for r in rows) / n, 3) if n else None,
               "mean_words_A": round(sum(r["A_words"] for r in rows) / n, 1) if n else None,
               "mean_words_B": round(sum(r["B_words"] for r in rows) / n, 1) if n else None}
    p = write_results("ab_test", {"provenance": provenance({"per_persona": a.per_persona}), "summary": summary, "rows": rows})
    print(json.dumps(summary, indent=1))
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
