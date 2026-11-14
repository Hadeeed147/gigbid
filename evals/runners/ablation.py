"""R&D question B, ablation: remove one component of the shipped pipeline at a time
and re-measure decisions, unsupported claims, judge score and GigSim reply rate.

Configurations (env overrides read by agent/config.yaml):
  full            shipped config (V8 corrective retrieval, claim verification, critic)
  -corrective     V4 instead of V8 (no re-query / refuse-to-claim loop)
  -outcome_boost  V3 instead of V8 (no outcome-aware ranking either)
  -rerank         V2 (hybrid only)
  -verification   claim verification off
  -critic         critic off (no revision loop)

Run:  GIGBID_LLM_CACHE=1 uv run python -m evals.runners.ablation --per-persona 15
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os

from common.config import reload_config
from evals.runners.common import mean, provenance, write_results

CONFIGS = {
    "full": {},
    "-corrective": {"GIGBID_RAG_VARIANT": "v4_outcome"},
    "-outcome_boost": {"GIGBID_RAG_VARIANT": "v3_rerank"},
    "-rerank": {"GIGBID_RAG_VARIANT": "v2_hybrid"},
    "-verification": {"GIGBID_VERIFY": "off"},
    "-critic": {"GIGBID_CRITIC": "off"},
}
KEYS = ("GIGBID_RAG_VARIANT", "GIGBID_VERIFY", "GIGBID_CRITIC")


def apply(env: dict) -> None:
    for k in KEYS:
        os.environ.pop(k, None)
    os.environ.update(env)
    reload_config()
    import rag.retriever as r
    r.get_store.cache_clear()


async def judge_scores(records: list[dict]) -> float | None:
    from agent.nodes.writer import strip_citations
    from evals.runners.judge_calibration import judge
    scores = []
    for r in records:
        if r.get("cover_letter"):
            try:
                scores.append(judge(r["job_id"], "", strip_citations(r["cover_letter"])).score)
            except Exception:  # noqa: BLE001
                pass
    return mean(scores)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-persona", type=int, default=15)
    ap.add_argument("--configs", default=",".join(CONFIGS))
    ap.add_argument("--no-judge", action="store_true")
    a = ap.parse_args()
    from evals.runners.decision_eval import evaluate
    table = {}
    for name in a.configs.split(","):
        apply(CONFIGS[name])
        res = asyncio.run(evaluate(a.per_persona, True, 3, f"ablation_{name}"))
        s = res["summary"]["overall"]
        props = [r for r in res["records"] if r.get("drafted")]
        table[name] = {"bid_f1": s["bid_f1"], "unsupported_before": s["unsupported_claims_per_proposal_before"],
                       "unsupported_after": s["unsupported_claims_per_proposal_after"],
                       "judge_score": None if a.no_judge else asyncio.run(judge_scores(props)),
                       "gigsim_reply_rate": res["summary"]["gigsim_outcomes"]["overall"]["reply_rate"],
                       "p95_latency_per_proposal_s": s["latency_per_proposal_p95_s"],
                       "usd_per_proposal": s["usd_per_proposal"], "n_proposals": s["n_proposals"]}
        print(name, table[name])
    apply({})
    p = write_results("ablation", {"provenance": provenance({"per_persona": a.per_persona}), "summary": table})
    print(json.dumps(table, indent=1))
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
