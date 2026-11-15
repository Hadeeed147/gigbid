"""Proposal Writer: cover letter + screening answers with evidence citations."""
from __future__ import annotations

import re

from agent.handoffs import ProposalDraft
from agent.memory.store import outcome_lessons, style_rules
from agent.nodes._runtime import job_text, node, untrusted
from common.config import cfg
from common.llm import chat
from common.prompts import load_prompt

CITE = re.compile(r"\[([a-z_]+:[a-z_]+:[^\]\s]+)\]")


def evidence_block(state: dict, max_items: int = 10) -> tuple[str, set[str]]:
    lines, ids = [], set()
    fit = state.get("fit", {})
    strong = {i for m in fit.get("matrix", []) for i in m.get("evidence_ids", [])}
    for req, items in (state.get("evidence") or {}).items():
        for e in items:
            if e["item_id"] in ids or len(ids) >= max_items:
                continue
            if strong and e["item_id"] not in strong and len(ids) >= max_items // 2:
                continue
            ids.add(e["item_id"])
            lines.append(f"[{e['item_id']}] ({e['type']}; for: {req[:60]}) {e['text'][:450]}")
    return "\n\n".join(lines), ids


async def fetch_exemplars(state: dict, k: int = 2) -> list[dict]:
    """Past proposals for similar jobs that WON or got REPLIES (outcome-aware phrasing, V4).
    They are style references only, never evidence: the writer prompt says so."""
    from agent.mcp_client import get_hub
    hub = await get_hub()
    q = state["job"].get("title", "") + " " + " ".join((state.get("job_spec") or {}).get("requirements", [])[:4])
    out: list[dict] = []
    for outcome in ("won", "replied"):
        if len(out) >= k:
            break
        res = await hub.call("writer", "search_evidence", {"requirement": q[:480], "k": k,
                                                            "filters": {"types": ["proposal"], "outcome": outcome}})
        out += res.get("items", [])
    return out[:k]


@node("writer")
async def writer(state: dict) -> dict:
    profile = state.get("profile", {})
    ev, ids = evidence_block(state)
    rules = style_rules(state.get("user_id", ""))
    lessons = outcome_lessons(state.get("user_id", ""), state["job"].get("category", ""))
    exemplars = "\n---\n".join(e["text"][:500] for e in await fetch_exemplars(state)) or "(none yet)"
    prompt_name = "writer_b" if str(cfg("proposal.strategy", "A")).upper() == "B" else "writer"
    sys = load_prompt(prompt_name, untrusted=load_prompt("_untrusted"), freelancer_name=profile.get("name", "the freelancer"),
                      freelancer_title=profile.get("title", ""), min_words=str(cfg("proposal.min_words")),
                      max_words=str(cfg("proposal.max_words")),
                      style_rules=("Learned style rules from this user's edits (follow them):\n- " + "\n- ".join(rules))
                      if rules else "", exemplars=exemplars)
    spec = state.get("job_spec", {})
    price = state.get("price", {})
    critiques = state.get("critiques") or []
    fix = ""
    if critiques:
        last = critiques[-1]
        fix = "\n\nREVISION REQUEST from the critic (fix every issue):\n" + "\n".join(
            f"- {i['problem']} -> {i['fix']}" for i in last.get("issues", []))
        fix += "\n\nPrevious draft:\n" + state.get("draft", {}).get("cover_letter", "")
    user = (untrusted("job_post", job_text(state["job"])) +
            f"\n\nRequirements (from the analyst): {spec.get('requirements', [])}"
            f"\nHidden needs: {spec.get('hidden_needs', [])}"
            f"\nScreening questions to answer, in order: {spec.get('screening_questions') or state['job'].get('screening_questions', [])}"
            f"\nProposed price: {price.get('amount')} ({price.get('unit')})"
            f"\nOutcome lessons for this category: {lessons or 'none yet'}"
            f"\n\nEVIDENCE (cite these ids only):\n{ev or '(no evidence: do not claim experience)'}{fix}")
    draft = chat("writer", [{"role": "system", "content": sys}, {"role": "user", "content": user}], ProposalDraft)
    cited = sorted(set(CITE.findall(draft.cover_letter + " ".join(draft.screening_answers))))
    draft.cited_ids = [c for c in cited if c in ids]
    draft.revision = state.get("revision", 0)
    return {"draft": draft.model_dump(), "status": "verifying"}


def strip_citations(text: str) -> str:
    """The client never sees [item ids]; the UI shows them as hover evidence instead."""
    return re.sub(r"\s?\[[a-z_]+:[a-z_]+:[^\]\s]+\]", "", text)
