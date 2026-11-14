"""Long-term memory on a LangGraph store (PostgresStore in production,
InMemoryStore in tests/evals). Two promoted stores per user:

  ("style", user)    promoted style rules       <- user edits, via promote_style
  ("outcome", user)  per-category outcome lessons <- marketplace outcomes, via promote_outcomes

Candidates and observations live in separate staging namespaces and are never
read by agents. The memory viewer in the UI lists and deletes promoted items.
"""
from __future__ import annotations

import time
import uuid

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from agent.memory.promotion_rules import extract_candidates, promote_outcomes, promote_style

_STORE: BaseStore = InMemoryStore()


def set_store(store: BaseStore) -> None:
    global _STORE
    _STORE = store


def get_store() -> BaseStore:
    return _STORE


# ---------------------------------------------------------------- style memory
def record_edit(user: str, before: str, after: str) -> list[dict]:
    """Stage candidates from one edit, then apply the promotion rule. Returns newly promoted rules."""
    if not user or before.strip() == after.strip():
        return []
    edit_id = uuid.uuid4().hex[:8]
    ns = ("style_candidates", user)
    for c in extract_candidates(before, after):
        item = _STORE.get(ns, c["key"])
        val = item.value if item else {"rule": c["rule"], "edits": []}
        val["edits"] = sorted(set(val["edits"]) | {edit_id})
        _STORE.put(ns, c["key"], val)
    counts = {it.key: it.value for it in _STORE.search(ns, limit=1000)}
    deleted = {it.key for it in _STORE.search(("style_deleted", user), limit=1000)}
    new = []
    existing = {it.key for it in _STORE.search(("style", user), limit=1000)}
    for r in promote_style(counts):
        if r["key"] in deleted or r["key"] in existing:
            continue
        _STORE.put(("style", user), r["key"], {"rule": r["rule"], "support": r["support"], "promoted_at": time.time(),
                                               "promotion_rule": "seen in >= style_min_support distinct edits"})
        new.append(r)
    return new


def style_rules(user: str) -> list[str]:
    if not user:
        return []
    return [it.value["rule"] for it in _STORE.search(("style", user), limit=50)]


# -------------------------------------------------------------- outcome memory
def record_outcome(user: str, obs: dict) -> dict:
    ns = ("outcome_obs", user)
    _STORE.put(ns, obs.get("proposal_id") or uuid.uuid4().hex, obs)
    all_obs = [it.value for it in _STORE.search(ns, limit=5000)]
    lessons = promote_outcomes(all_obs)
    for cat, lesson in lessons.items():
        _STORE.put(("outcome", user), cat, {**lesson, "promoted_at": time.time(),
                                            "promotion_rule": "category has >= outcome_min_samples outcomes"})
    return lessons


def outcome_lessons(user: str, category: str) -> str:
    if not user or not category:
        return ""
    it = _STORE.get(("outcome", user), category)
    if not it:
        return ""
    v = it.value
    s = f"{v['n']} past proposals in {category}: reply rate {v['reply_rate']:.0%}, hire rate {v['hire_rate']:.0%}"
    if v.get("reply_rate_with_2plus_citations") is not None:
        s += f"; with 2+ cited pieces of evidence the reply rate was {v['reply_rate_with_2plus_citations']:.0%}"
    return s


# --------------------------------------------------------------- memory viewer
def list_memory(user: str) -> dict[str, list[dict]]:
    return {"style": [{"key": it.key, **it.value} for it in _STORE.search(("style", user), limit=100)],
            "outcome": [{"key": it.key, **it.value} for it in _STORE.search(("outcome", user), limit=100)]}


def delete_memory(user: str, kind: str, key: str) -> bool:
    ns = (kind, user)
    if not _STORE.get(ns, key):
        return False
    _STORE.delete(ns, key)
    if kind == "style":   # remember the deletion so the same rule is not silently re-promoted
        _STORE.put(("style_deleted", user), key, {"deleted_at": time.time()})
    return True
