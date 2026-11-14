"""30-job smoke eval for CI, with failure thresholds (E2).

Runs the bid graph on 10 dev jobs per persona and FAILS (exit 1) if
  * bid-or-skip F1 drops below thresholds.min_bid_f1, or
  * unsupported claims per proposal (after verification) rise above thresholds.max_unsupported_after.
Uses the real open profile when GROQ_API_KEY is set, otherwise the deterministic
test double (then only pipeline health is checked, not model quality).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from evals.runners.common import provenance, write_results

THRESHOLDS = {"real": {"min_bid_f1": 0.55, "max_unsupported_after": 0.5},
              "fake": {"min_bid_f1": 0.40, "max_unsupported_after": 0.5}}


def main() -> None:
    mode = "real" if os.environ.get("GROQ_API_KEY") and os.environ.get("GIGBID_FAKE_LLM") != "1" else "fake"
    if mode == "fake":
        os.environ["GIGBID_FAKE_LLM"] = "1"
    from evals.runners.decision_eval import evaluate
    res = asyncio.run(evaluate(10, False, 3, "smoke"))
    s = res["summary"]["overall"]
    th = THRESHOLDS[mode]
    fails = []
    if (s["bid_f1"] or 0) < th["min_bid_f1"]:
        fails.append(f"bid_f1 {s['bid_f1']} < {th['min_bid_f1']}")
    ua = s["unsupported_claims_per_proposal_after"]
    if ua is not None and ua > th["max_unsupported_after"]:
        fails.append(f"unsupported_after {ua} > {th['max_unsupported_after']}")
    if s["n_failed"] > 3:
        fails.append(f"{s['n_failed']} jobs failed")
    out = {"provenance": provenance({"mode": mode, "thresholds": th}), "summary": s, "failures": fails}
    if mode == "real":
        write_results("smoke_eval", out)
    print(json.dumps(out, indent=1, default=str))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
