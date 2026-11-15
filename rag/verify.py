"""Claim verification (B3, required).

1. Split the draft into sentences; keep the ones that assert experience or
   results as claims (plans, questions and greetings are not claims).
2. For each claim, gather candidate evidence: the evidence the writer was given
   plus a fresh hybrid search over the whole tenant portfolio.
3. Grade each claim supported / partly_supported / unsupported with the LLM
   (grader="llm") or the cross-encoder (grader="ce", no API cost).
4. Remove unsupported claims; rewrite partly supported ones to what the evidence
   shows. Report the unsupported-claim rate before and after.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from common.config import cfg
from common.prompts import load_prompt
from rag.index.embed import rerank, sigmoid

CLAIM_HINT = re.compile(
    r"(?i)\b(i|i've|i have|i'm|my|we)\b.*\b(built|build|developed|designed|delivered|shipped|created|led|used|worked|"
    r"implemented|trained|deployed|migrated|automated|reduced|cut|improved|increased|lifted|grew|have|experience|"
    r"years|handled|wrote|integrated|fine-tuned)\b|\b\d+(\.\d+)?\s?(%|x|k|ms|hours|users|clients)\b")


class ClaimVerdict(BaseModel):
    status: Literal["supported", "partly_supported", "unsupported"]
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    rewrite: str | None = Field(default=None, description="For partly_supported: the claim rewritten to match evidence")


class ClaimResult(BaseModel):
    text: str
    status: str
    evidence_ids: list[str] = []
    reason: str = ""
    rewrite: str | None = None


class VerificationReport(BaseModel):
    claims: list[ClaimResult]
    unsupported_before: int
    unsupported_after: int
    claims_total: int
    revised_text: str

    @property
    def unsupported_rate_before(self) -> float:
        return self.unsupported_before / self.claims_total if self.claims_total else 0.0


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])|\n{2,}", text.strip())
    return [p.strip() for p in parts if p and p.strip()]


def is_claim(sentence: str) -> bool:
    s = sentence.strip()
    if s.endswith("?") or len(s.split()) < 4:
        return False
    if re.match(r"(?i)^(i would|i will|i'd|i can|happy to|let's|could we|thanks|thank you|looking forward)", s):
        return False
    return bool(CLAIM_HINT.search(s))


def _candidates(tenant: str, claim: str, given: list[dict], k: int = 6) -> list[dict]:
    from rag.retriever import get_store, lite_mode
    from rag.variants.v2_hybrid import V2Hybrid
    pool = {e["item_id"]: e for e in given}
    if lite_mode():  # no models on the 512 MB host: keyword candidates, the LLM grader decides
        for h in get_store().structured(tenant).sparse(claim, k):
            pool.setdefault(h.item_id, h.to_evidence())
        return list(pool.values())[:4]
    for h in V2Hybrid(get_store()).candidates(tenant, claim)[:k]:
        pool.setdefault(h.item_id, h.to_evidence())
    docs = list(pool.values())
    scores = rerank(claim, [d.get("title", "") + "\n" + d["text"] for d in docs])
    ranked = sorted(zip(docs, scores, strict=True), key=lambda x: -x[1])[:4]
    return [{**d, "ce": round(sigmoid(s), 3)} for d, s in ranked]


def _grade_ce(cands: list[dict]) -> ClaimVerdict:
    # lite mode has no cross-encoder score: then every claim is graded unsupported (removed), never kept unchecked
    top = cands[0].get("ce", 0.0) if cands else 0.0
    ids = [c["item_id"] for c in cands if c.get("ce", 0.0) >= 0.15][:2]
    if top >= 0.5:
        return ClaimVerdict(status="supported", evidence_ids=ids, reason=f"cross-encoder {top}")
    if top >= 0.15:
        return ClaimVerdict(status="partly_supported", evidence_ids=ids, reason=f"cross-encoder {top}")
    return ClaimVerdict(status="unsupported", reason=f"best evidence score {top}")


def _grade_llm(claim: str, cands: list[dict]) -> ClaimVerdict:
    from common.llm import chat
    ev = "\n\n".join(f"[{c['item_id']}] ({c['type']}) {c['text'][:700]}" for c in cands)
    prompt = load_prompt("verifier")
    return chat("verifier", [{"role": "system", "content": prompt},
                             {"role": "user", "content": f"<claim>{claim}</claim>\n\n<evidence>\n{ev}\n</evidence>"}],
                ClaimVerdict)


def verify(text: str, tenant: str, given_evidence: list[dict], grader: str | None = None) -> VerificationReport:
    grader = grader or cfg("verify.grader", "llm")
    sentences = split_sentences(text)
    results: list[ClaimResult] = []
    kept: list[str] = []
    for s in sentences:
        if not is_claim(s):
            kept.append(s)
            continue
        cands = _candidates(tenant, s, given_evidence)
        try:
            v = _grade_llm(s, cands) if grader == "llm" else _grade_ce(cands)
        except Exception as e:  # LLM unavailable -> fall back to the free grader
            v = _grade_ce(cands)
            v.reason += f" (llm grader failed: {type(e).__name__})"
        results.append(ClaimResult(text=s, **v.model_dump()))
        if v.status == "supported":
            kept.append(s)
        elif v.status == "partly_supported" and v.rewrite:
            kept.append(v.rewrite)
        # unsupported: removed
    before = sum(1 for r in results if r.status == "unsupported")
    revised = "\n\n".join(kept) if "\n\n" in text else " ".join(kept)
    return VerificationReport(claims=results, unsupported_before=before, unsupported_after=0,
                              claims_total=len(results), revised_text=revised)
