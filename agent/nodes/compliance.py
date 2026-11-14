"""Compliance Guard: enforce the policy pack. Pattern rules from
data/policy_pack/policy.yaml run first (deterministic, cannot be argued with);
the LLM then catches paraphrased violations. No MCP access."""
from __future__ import annotations

import re
from functools import lru_cache

import yaml

from agent.handoffs import ComplianceVerdict, Violation
from agent.nodes._runtime import node
from common.config import cfg, resolve_path
from common.llm import chat
from common.prompts import load_prompt


@lru_cache(maxsize=1)
def policy_pack() -> dict:
    return yaml.safe_load(resolve_path(cfg("policy_pack")).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def banned_phrases() -> list[str]:
    p = resolve_path(cfg("proposal.banned_phrases_file"))
    return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]


def rule_check(text: str, extra_banned: list[str] | None = None) -> tuple[list[Violation], str, bool]:
    """Returns (violations, cleaned_text, must_block)."""
    violations, cleaned = [], text
    for rule in policy_pack()["rules"]:
        for pat in rule.get("patterns", []):
            for m in re.finditer(pat, cleaned):
                violations.append(Violation(rule=rule["id"], quote=m.group(0)[:80]))
            if re.search(pat, cleaned):
                # drop every sentence that carries the violation, keep paragraph breaks
                paras = []
                for para in cleaned.split("\n\n"):
                    sentences = re.split(r"(?<=[.!?])\s+", para)
                    paras.append(" ".join(s for s in sentences if not re.search(pat, s)))
                cleaned = "\n\n".join(p for p in paras if p.strip())
    for phrase in banned_phrases() + (extra_banned or []):
        if phrase.lower() in cleaned.lower():
            violations.append(Violation(rule="banned_phrase", quote=phrase))
            cleaned = re.sub(re.escape(phrase), "", cleaned, flags=re.I)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    # if removing violations gutted the text, it cannot be salvaged automatically
    block = bool(violations) and len(cleaned) < 0.5 * len(text)
    return violations, cleaned, block


def check_text(text: str, *, use_llm: bool = True) -> ComplianceVerdict:
    violations, cleaned, block = rule_check(text)
    if use_llm:
        pol = "\n".join(f"- {r['id']}: {r['description']}" for r in policy_pack()["rules"])
        llm = chat("compliance", [{"role": "system", "content": load_prompt("compliance", policy=pol)},
                                  {"role": "user", "content": f"<text>\n{cleaned}\n</text>"}], ComplianceVerdict)
        violations += llm.violations
        if llm.verdict == "block":
            block = True
        if llm.verdict == "rewrite" and llm.cleaned_text and len(llm.cleaned_text) > 0.6 * len(cleaned):
            cleaned = llm.cleaned_text
    verdict = "block" if block else ("rewrite" if violations else "pass")
    return ComplianceVerdict(verdict=verdict, violations=violations, cleaned_text=cleaned)


@node("compliance")
async def compliance(state: dict) -> dict:
    draft = dict(state["draft"])
    from agent.nodes._runtime import defenses_on
    if not defenses_on():
        return {"compliance": {"verdict": "skipped", "violations": []}, "status": "awaiting_approval"}
    v = check_text(draft["cover_letter"])
    answers = [check_text(a, use_llm=False).cleaned_text or a for a in draft.get("screening_answers", [])]
    if v.verdict == "block":
        return {"compliance": v.model_dump(), "status": "blocked",
                "attention_reason": "Compliance Guard blocked: " + "; ".join(f"{x.rule}: {x.quote}" for x in v.violations)}
    draft["cover_letter"] = v.cleaned_text or draft["cover_letter"]
    draft["screening_answers"] = answers
    return {"compliance": v.model_dump(), "draft": draft, "status": "awaiting_approval"}
