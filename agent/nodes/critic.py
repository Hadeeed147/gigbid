"""Critic: grounding, personalisation, coverage, length. Sends back at most twice."""
from __future__ import annotations

from agent.handoffs import Critique, CritiqueIssue
from agent.nodes._runtime import job_text, node, untrusted
from agent.nodes.writer import CITE
from common.config import cfg
from common.llm import chat
from common.prompts import load_prompt
from gigsim.client_model import is_generic_opening


def hard_checks(draft: dict) -> list[CritiqueIssue]:
    text = draft.get("cover_letter", "")
    n = len(CITE.sub("", text).split())
    issues = []
    if n < cfg("proposal.min_words"):
        issues.append(CritiqueIssue(problem=f"too short ({n} words)", fix="add one more specific piece of evidence"))
    if n > cfg("proposal.max_words") + 30:
        issues.append(CritiqueIssue(problem=f"too long ({n} words)", fix=f"cut to under {cfg('proposal.max_words')} words"))
    if is_generic_opening(CITE.sub("", text)):
        issues.append(CritiqueIssue(problem="generic opening", fix="open with the client's problem and your best evidence"))
    if not CITE.search(text):
        issues.append(CritiqueIssue(problem="no evidence citations", fix="cite evidence ids for each claim"))
    return issues


@node("critic")
async def critic(state: dict) -> dict:
    draft = state["draft"]
    if str(cfg("pipeline.critic", "on")).lower() == "off":   # ablation only
        return {"critiques": [{"approved": True, "score": 0, "issues": [], "revision": 0, "skipped": True}],
                "status": "critiqued"}
    sys = load_prompt("critic", min_words=str(cfg("proposal.min_words")), max_words=str(cfg("proposal.max_words")))
    ver = state.get("verification", {})
    c = chat("critic", [{"role": "system", "content": sys},
                        {"role": "user", "content": untrusted("job_post", job_text(state["job"])) +
                         f"\n\nDRAFT:\n{draft['cover_letter']}\n\nSCREENING ANSWERS:\n{draft.get('screening_answers')}"
                         f"\n\nClaim verification removed {ver.get('unsupported_before', 0)} unsupported claim(s)."}],
             Critique)
    hard = hard_checks(draft)
    if hard:
        c.issues = hard + c.issues
        c.approved = False
    rev = state.get("revision", 0)
    out = {"critiques": [c.model_dump() | {"revision": rev}], "status": "critiqued"}
    if not c.approved and rev < cfg("loops.max_critic_revisions", 2):
        out["revision"] = rev + 1
    return out
