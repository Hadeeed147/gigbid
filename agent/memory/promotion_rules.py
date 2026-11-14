"""Explicit promotion rules (R7). Nothing reaches long-term memory without passing one.

Style memory (learned from the user's edits to drafts)
  1. Each edit is turned into *candidate observations* by deterministic
     extractors below (removed phrase, cut first sentence, shortened, no
     exclamation marks, ends with a question...). Raw diffs are never stored as rules.
  2. A candidate is PROMOTED to a style rule only when it has been observed in
     at least `memory.style_min_support` DISTINCT edits, and it does not
     contradict the policy pack (e.g. a rule can never ask to add contact details).

Outcome memory (learned from marketplace results)
  1. Each submitted proposal's outcome (replied / hired / ignored) is recorded as
     an observation with simple features (category, opening style, citations).
  2. A lesson for a category is PROMOTED only once the category has at least
     `memory.outcome_min_samples` outcomes, and only as aggregate rates, never as
     copied client text.
"""
from __future__ import annotations

import re
from collections import Counter

from common.config import cfg

FORBIDDEN_RULE = re.compile(r"(?i)(email|phone|whatsapp|telegram|guarantee|paypal|off-platform)")


def _sentences(t: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", t.strip()) if s.strip()]


STOPWORDS = set("""a an the and or but if then so to of in on at by for with from into over about as is are was were
be been being i me my we our you your it its this that these those have has had do does did will would can could should
may might must not no just also very really more most some any all each other such than too here there what which who
whom how when where why up out off again once only own same both few""".split())
# Filler words that carry no information; when a user deletes a whole sentence these are the only
# word-level lessons we take from it (the rest of the sentence was content, not style).
FILLER = {"passionate", "excited", "dedicated", "hardworking", "hard-working", "guru", "ninja", "rockstar", "expert",
          "perfect", "best", "amazing", "awesome", "seamless", "cutting-edge", "synergy", "leverage", "delighted",
          "thrilled", "honest", "reliable", "dear", "sir", "madam", "greetings", "kindly"}


def _words(t: str) -> list[str]:
    return re.findall(r"[a-z][a-z'-]*", t.lower())


def extract_candidates(before: str, after: str) -> list[dict]:
    """Deterministic observations from one edit. Each has a stable key and a rule text.

    Sentences are aligned with difflib. Words deleted INSIDE a kept sentence are
    style signals; whole deleted sentences only yield filler words (their other
    words were content, not style) and the cut-first-sentence pattern.
    """
    import difflib

    out: dict[str, str] = {}
    b_s, a_s = _sentences(before), _sentences(after)
    sm = difflib.SequenceMatcher(a=[s.lower() for s in b_s], b=[s.lower() for s in a_s], autojunk=False)
    removed_words: set[str] = set()
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "delete":
            if i1 == 0 and i2 < len(b_s):
                out["cut_first_sentence"] = "Cut the first sentence: start with the second, more specific point."
            for s in b_s[i1:i2]:
                removed_words |= {w for w in _words(s) if w in FILLER}
        elif op == "replace":
            kept = set(_words(" ".join(a_s[j1:j2])))
            for s in b_s[i1:i2]:
                removed_words |= {w for w in _words(s) if w not in kept and w not in STOPWORDS and len(w) > 3}
            if i1 == 0 and len(_words(a_s[j1])) < 0.6 * len(_words(b_s[i1])):
                out.setdefault("tighter_opening", "Keep the opening sentence short and specific.")
    after_words = set(_words(after))
    for w in sorted(removed_words - after_words)[:8]:
        out[f"avoid:{w}"] = f'Never say "{w}".'
    b_n, a_n = len(before.split()), len(after.split())
    if b_n and a_n < 0.8 * b_n:
        out["shorter"] = f"Keep proposals short (around {max(60, round(a_n, -1))} words)."
    if "!" in before and "!" not in after:
        out["no_exclamations"] = "Do not use exclamation marks."
    if not before.rstrip().endswith("?") and after.rstrip().endswith("?"):
        out["end_with_question"] = "End with a direct question to the client."
    return [{"key": k, "rule": r} for k, r in out.items()]


def promote_style(candidate_counts: dict[str, dict]) -> list[dict]:
    """candidate_counts: key -> {"rule": str, "edits": [edit ids]}. Returns promotable rules."""
    min_support = cfg("memory.style_min_support", 2)
    promoted = []
    for key, c in candidate_counts.items():
        support = len(set(c["edits"]))
        if support >= min_support and not FORBIDDEN_RULE.search(c["rule"]):
            promoted.append({"key": key, "rule": c["rule"], "support": support})
    promoted.sort(key=lambda r: -r["support"])
    return promoted[: cfg("memory.max_style_rules", 12)]


def promote_outcomes(observations: list[dict]) -> dict[str, dict]:
    """observations: [{category, outcome, opening_generic, n_citations}] -> category -> lesson."""
    min_n = cfg("memory.outcome_min_samples", 3)
    by_cat: dict[str, list[dict]] = {}
    for o in observations:
        by_cat.setdefault(o.get("category") or "Other", []).append(o)
    lessons = {}
    for cat, obs in by_cat.items():
        if len(obs) < min_n:
            continue
        outcomes = Counter(o["outcome"] for o in obs)
        replied = outcomes["replied"] + outcomes["interview"] + outcomes["hired"]
        cited = [o for o in obs if o.get("n_citations", 0) >= 2]
        cited_rate = sum(o["outcome"] != "ignored" for o in cited) / len(cited) if cited else None
        lessons[cat] = {"n": len(obs), "reply_rate": round(replied / len(obs), 2), "hire_rate": round(outcomes["hired"] / len(obs), 2),
                        "reply_rate_with_2plus_citations": round(cited_rate, 2) if cited_rate is not None else None}
    return lessons
