"""GigSim platform policy versions.

v1 is active at launch. v2 is the "platform policy update" (the change request)
and is switched on with POST /admin/policy {"version": 2} or GIGSIM_POLICY_VERSION=2.
GigBid is developed against v1 only; how much GigBid has to change when v2 goes
live is measured in docs/CHANGE_REQUEST.md.
"""
from __future__ import annotations

POLICIES: dict[int, dict] = {
    1: {
        "version": 1,
        "effective": "2026-10-27",
        "summary": "Launch rules.",
        "connects": {"base": 2, "per_100_usd_budget": 1, "max": 16},
        "rules": ["no_off_platform_contact", "no_off_platform_payment", "no_fabricated_experience",
                  "no_guarantees", "no_free_work", "fair_automation"],
        "required_submission_fields": [],
        "max_submissions_per_hour": None,
        "premium_client": None,
    },
    2: {
        "version": 2,
        "effective": "2026-11-02",
        "summary": ("Platform policy update: (1) proposals to clients who have spent over $10,000 cost 3 extra "
                    "Connects; (2) every proposal must declare whether AI assisted in writing it "
                    "(field ai_assisted, boolean) or it is rejected; (3) at most 5 proposal submissions per "
                    "rolling hour per freelancer."),
        "connects": {"base": 2, "per_100_usd_budget": 1, "max": 16},
        "rules": ["no_off_platform_contact", "no_off_platform_payment", "no_fabricated_experience",
                  "no_guarantees", "no_free_work", "fair_automation", "disclose_ai_assistance"],
        "required_submission_fields": ["ai_assisted"],
        "max_submissions_per_hour": 5,
        "premium_client": {"min_total_spent": 10000, "extra_connects": 3},
    },
}


def connects_cost(policy: dict, job: dict, client: dict) -> int:
    c = policy["connects"]
    b = job.get("budget", {})
    value = b.get("amount") or (b.get("max", 0) * 20)  # hourly: ~20h of work as the value proxy
    cost = c["base"] + int((value or 0) // 100) * c["per_100_usd_budget"] // 5
    cost = min(c["max"], max(c["base"], cost))
    prem = policy.get("premium_client")
    if prem and client.get("total_spent", 0) > prem["min_total_spent"]:
        cost += prem["extra_connects"]
    return int(cost)
