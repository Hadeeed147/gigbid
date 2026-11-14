"""R&D question B, retrieval half: compare RAG variants on the dev set.

Metrics per variant, persona and job type: evidence Recall@5 (capped, vs the
strongest gold evidence), MRR, nDCG@10 (graded), latency p50/p95.

Requirements come from the deterministic splitter by default (no LLM, fully
reproducible); --requirements llm uses cached Job Analyst JobSpecs instead.

Run:  uv run python -m evals.runners.rag_eval [--per-persona 120] [--variants v0_naive,v2_hybrid]
"""
from __future__ import annotations

import argparse
import csv
import time

from evals.runners.common import (
    PERSONAS,
    gold_items,
    load_dev,
    mean,
    mrr,
    ndcg_at_k,
    pctl,
    provenance,
    recall_at_k,
    write_results,
)
from rag.retriever import VARIANTS, get_store, get_variant
from rag.variants.base import RetrievalQuery, rule_requirements

KINDS = {"fit", "partial", "injection", "underpriced", "scam"}   # jobs with real gold evidence


def job_type(job: dict, n_req: int) -> str:
    if job["gold"].get("vague"):
        return "vague"
    return "4+ requirements" if n_req >= 4 else "1-3 requirements"


def run(variants: list[str], per_persona: int | None) -> dict:
    store = get_store()
    rows = []
    for persona in PERSONAS:
        jobs = [j for j in load_dev(persona, kinds=KINDS) if j["gold"]["relevant_projects"]
                and not j["gold"].get("duplicate_of")][:per_persona]
        for vname in variants:
            v = get_variant(vname)
            for job in jobs:
                text = job["title"] + "\n" + job["description"]
                reqs = rule_requirements(text)
                rel, strong = gold_items(job, store, persona)
                t0 = time.time()
                res = v.retrieve(RetrievalQuery(tenant=persona, job_text=text, requirements=reqs,
                                                category=job.get("category", "")), 10)
                lat = time.time() - t0
                ranked = [h.item_id for h in res.hits]
                rows.append({"variant": vname, "persona": persona, "job_id": job["id"],
                             "job_type": job_type(job, len(job["required_skills"])),
                             "n_requirements": len(job["required_skills"]),
                             "recall@5": recall_at_k(ranked, strong), "mrr": mrr(ranked, strong),
                             "ndcg@10": ndcg_at_k(ranked, rel), "latency_s": round(lat, 4)})
            print(f"{persona:13} {vname:14} n={len(jobs)} "
                  f"R@5={mean(r['recall@5'] for r in rows if r['variant'] == vname and r['persona'] == persona)}")

    def agg(filt) -> dict:
        sub = [r for r in rows if filt(r)]
        return {"n": len(sub), "recall@5": mean(r["recall@5"] for r in sub), "mrr": mean(r["mrr"] for r in sub),
                "ndcg@10": mean(r["ndcg@10"] for r in sub), "latency_p50_s": pctl([r["latency_s"] for r in sub], .5),
                "latency_p95_s": pctl([r["latency_s"] for r in sub], .95)}

    summary = {v: {"overall": agg(lambda r, v=v: r["variant"] == v),
                   "by_persona": {p: agg(lambda r, v=v, p=p: r["variant"] == v and r["persona"] == p) for p in PERSONAS},
                   "by_job_type": {t: agg(lambda r, v=v, t=t: r["variant"] == v and r["job_type"] == t)
                                   for t in ("1-3 requirements", "4+ requirements", "vague")}}
               for v in variants}
    return {"provenance": provenance({"requirements": "rule splitter", "per_persona": per_persona}),
            "summary": summary, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--per-persona", type=int, default=None)
    ap.add_argument("--name", default="rag_eval")
    a = ap.parse_args()
    out = run(a.variants.split(","), a.per_persona)
    p = write_results(a.name, out)
    with open(p.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["variant", "recall@5", "mrr", "ndcg@10", "latency_p50_s", "latency_p95_s", "n"])
        for v, s in out["summary"].items():
            o = s["overall"]
            w.writerow([v, o["recall@5"], o["mrr"], o["ndcg@10"], o["latency_p50_s"], o["latency_p95_s"], o["n"]])
    print(f"wrote {p}")
    for v, s in out["summary"].items():
        print(f"{v:14} {s['overall']}")


if __name__ == "__main__":
    main()
