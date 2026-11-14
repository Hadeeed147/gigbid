"""Calibrated LLM judge (B4).

  1. sheet : export 30 anonymised proposals (from decision_eval results) to
             evals/datasets/judge_labels.csv. YOU score each 1-10 in `human_score`
             using the rubric in agent/prompts/judge.md, without looking at the judge.
  2. score : run the judge on the same 30 and report Cohen's kappa (3 bands:
             1-4 weak, 5-7 ok, 8-10 strong) and quadratic-weighted kappa on raw scores.
  3. judge(): used by other runners once calibration is acceptable.

Run:  uv run python -m evals.runners.judge_calibration sheet
      (fill human_score)   then   uv run python -m evals.runners.judge_calibration score
"""
from __future__ import annotations

import csv
import json
import random
import sys

from pydantic import BaseModel, Field
from sklearn.metrics import cohen_kappa_score

from common.llm import chat
from common.prompts import load_prompt
from evals.runners.common import DATASETS, RESULTS, provenance, write_results

SHEET = DATASETS / "judge_labels.csv"


class JudgeScore(BaseModel):
    score: int = Field(ge=1, le=10)
    reason: str = ""


def judge(job_title: str, job_text: str, proposal: str) -> JudgeScore:
    return chat("judge", [{"role": "system", "content": load_prompt("judge")},
                          {"role": "user", "content": f"JOB: {job_title}\n{job_text[:1500]}\n\nPROPOSAL:\n{proposal}"}],
                JudgeScore)


def band(s: int) -> int:
    return 0 if s <= 4 else (1 if s <= 7 else 2)


def make_sheet(source: str = "decision_eval") -> None:
    data = json.loads((RESULTS / f"{source}.json").read_text(encoding="utf-8"))
    props = [r for r in data["records"] if r.get("cover_letter")]
    random.Random(4).shuffle(props)
    jobs = {}
    for p in ("ai_ml", "fullstack", "data_analyst"):
        for line in (DATASETS / f"dev_{p}.jsonl").read_text(encoding="utf-8").splitlines():
            j = json.loads(line)
            jobs[j["id"]] = j
    from agent.nodes.writer import strip_citations
    with SHEET.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item", "job_id", "job_title", "job_description", "proposal", "human_score"])
        for i, r in enumerate(props[:30]):
            j = jobs[r["job_id"]]
            w.writerow([i + 1, r["job_id"], j["title"], j["description"][:800], strip_citations(r["cover_letter"]), ""])
    print(f"wrote {SHEET}: score each row 1-10 in human_score (rubric: agent/prompts/judge.md)")


def score() -> None:
    rows = list(csv.DictReader(SHEET.open(encoding="utf-8")))
    labelled = [r for r in rows if r["human_score"].strip()]
    if len(labelled) < 30:
        sys.exit(f"only {len(labelled)}/30 rows have human_score; label all 30 first")
    human, model, items = [], [], []
    for r in labelled:
        js = judge(r["job_title"], r["job_description"], r["proposal"])
        h = int(float(r["human_score"]))
        human.append(h)
        model.append(js.score)
        items.append({"item": r["item"], "job_id": r["job_id"], "human": h, "judge": js.score, "judge_reason": js.reason})
    out = {"provenance": provenance({"n": len(items)}),
           "summary": {"cohen_kappa_3band": round(cohen_kappa_score([band(x) for x in human], [band(x) for x in model]), 3),
                       "quadratic_weighted_kappa": round(cohen_kappa_score(human, model, weights="quadratic"), 3),
                       "mean_human": round(sum(human) / len(human), 2), "mean_judge": round(sum(model) / len(model), 2),
                       "largest_disagreements": sorted(items, key=lambda x: -abs(x["human"] - x["judge"]))[:5]},
           "items": items}
    p = write_results("judge_calibration", out)
    print(json.dumps(out["summary"], indent=1))
    print(f"wrote {p}")


if __name__ == "__main__":
    {"sheet": make_sheet, "score": score}[sys.argv[1] if len(sys.argv) > 1 else "sheet"]()
