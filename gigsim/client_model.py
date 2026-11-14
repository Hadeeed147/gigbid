"""Simulated client behaviour for GigSim.

Each client has hidden preferences (must-have skills, budget ceiling, dislike of
generic openings, responsiveness). Given a submitted proposal the client decides
viewed -> replied -> interview -> hired, deterministically for a given
(job, proposal text) pair so reply rates are reproducible across eval runs.

Mode "rules" (default) is a transparent scoring function. Mode "llm" asks an
LLM to role-play the client with the same hidden preferences (see server.py).
"""
from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass

GENERIC_OPENINGS = [
    r"^\s*(dear|hello|hi)\s+(sir|madam|sir/madam|hiring manager)",
    r"i am writing to (apply|express)",
    r"i am (very )?passionate",
    r"i have read your job (post|description)",
    r"i am the (best|perfect) (fit|candidate)",
    r"i am a (highly )?(skilled|experienced) (professional|developer|freelancer)",
    r"greetings",
]
OFF_PLATFORM = re.compile(
    r"(whatsapp|telegram|skype|gmail\.com|@[a-z0-9-]+\.[a-z]{2,}|\+?\d[\d\s-]{8,}\d|wechat|signal app)", re.I
)


@dataclass
class Decision:
    score: float
    viewed: bool
    replied: bool
    interview: bool
    hired: bool
    reasons: list[str]


def _rng(*parts: str) -> random.Random:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def is_generic_opening(text: str) -> bool:
    first = text.strip().split("\n", 1)[0][:240].lower()
    return any(re.search(p, first) for p in GENERIC_OPENINGS)


def _mentions(text: str, terms: list[str]) -> int:
    low = text.lower()
    return sum(1 for t in terms if t and t.lower() in low)


def decide(
    *,
    job: dict,
    client: dict,
    proposal_text: str,
    bid_amount: float,
    screening_answers: list[str] | None = None,
    skill_names: dict[str, list[str]] | None = None,
) -> Decision:
    """Score a proposal against the client's hidden preferences."""
    prefs = client.get("hidden_prefs", {})
    reasons: list[str] = []
    words = len(proposal_text.split())
    score = 0.18 + 0.25 * client.get("responsiveness", 0.6)

    must = prefs.get("must_have", [])
    if must and skill_names:
        hit = sum(1 for s in must if _mentions(proposal_text, skill_names.get(s, [s])) > 0)
        frac = hit / len(must)
        score += 0.30 * frac
        reasons.append(f"must-have coverage {hit}/{len(must)}")

    job_terms = [w for w in re.findall(r"[A-Za-z][A-Za-z+.#-]{4,}", job.get("title", ""))][:6]
    if _mentions(proposal_text, job_terms) >= 2:
        score += 0.10
        reasons.append("personalised to the post")

    # evidence signals: numbers / concrete outcomes
    if re.search(r"\b\d+(\.\d+)?\s?(%|x|ms|hours|users|clients|rows|k\b)", proposal_text, re.I):
        score += 0.07
        reasons.append("concrete results")

    qs = job.get("screening_questions", [])
    if qs:
        answered = len([a for a in (screening_answers or []) if a and len(a.split()) >= 8])
        score += 0.08 * (answered / len(qs))

    ceiling = prefs.get("budget_ceiling")
    if ceiling and bid_amount > ceiling:
        score -= 0.30
        reasons.append("over budget ceiling")

    if is_generic_opening(proposal_text):
        score -= 0.25 if prefs.get("dislikes_generic", True) else 0.05
        reasons.append("generic opening")

    if words > 320 or words < 45:
        score -= 0.15
        reasons.append("length outside client's patience")

    if OFF_PLATFORM.search(proposal_text):
        score -= 0.45
        reasons.append("off-platform contact (policy violation)")

    score = max(0.0, min(1.0, score))
    rng = _rng(job.get("id", ""), proposal_text.strip()[:2000])
    viewed = rng.random() < 0.55 + 0.4 * client.get("responsiveness", 0.6)
    replied = viewed and rng.random() < score
    interview = replied and rng.random() < max(0.0, score - 0.15) * 1.2
    hired = interview and rng.random() < 0.45 + 0.3 * score
    return Decision(score=round(score, 3), viewed=viewed, replied=replied, interview=interview, hired=hired,
                    reasons=reasons)
