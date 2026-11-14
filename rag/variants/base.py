"""Shared variant interface and helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from data.generators.skills import SKILLS
from rag.ingest.loaders import tag_skills
from rag.types import Hit

EVIDENCE_TYPES = {"case_study", "readme", "code", "review", "cv"}


@dataclass
class RetrievalQuery:
    tenant: str
    job_text: str
    requirements: list[str] = field(default_factory=list)
    category: str = ""


@dataclass
class RetrievalResult:
    hits: list[Hit]                                   # merged, de-duplicated by item, ranked
    per_requirement: dict[str, list[Hit]] = field(default_factory=dict)
    support: dict[str, str] = field(default_factory=dict)   # requirement -> supported | weak | none
    exemplars: list[dict] = field(default_factory=list)     # won/replied proposals for phrasing (V4)
    notes: list[str] = field(default_factory=list)

    def evidence(self, k: int | None = None) -> list[dict]:
        return [h.to_evidence() for h in (self.hits[:k] if k else self.hits)]


def rule_requirements(job_text: str) -> list[str]:
    """Deterministic requirement extraction (fallback when no LLM JobSpec exists)."""
    bullets = [ln.strip("-*• \t") for ln in job_text.splitlines() if re.match(r"^\s*[-*•]\s+\S", ln)]
    if bullets:
        return bullets[:8]
    sents = re.split(r"(?<=[.!?])\s+", job_text)
    with_skill = [s for s in sents if tag_skills(s)]
    return (with_skill or sents)[:6]


def dedupe_by_item(hits: list[Hit]) -> list[Hit]:
    seen, out = set(), []
    for h in hits:
        if h.item_id in seen:
            continue
        seen.add(h.item_id)
        out.append(h)
    return out


def round_robin(per_req: dict[str, list[Hit]], k: int) -> list[Hit]:
    """Interleave per-requirement rankings so every requirement gets evidence."""
    lists = [lst for lst in per_req.values() if lst]
    out: list[Hit] = []
    seen: set[str] = set()
    depth = 0
    while len(out) < k and any(depth < len(lst) for lst in lists):
        for lst in lists:
            if depth < len(lst) and lst[depth].item_id not in seen:
                seen.add(lst[depth].item_id)
                out.append(lst[depth])
                if len(out) >= k:
                    break
        depth += 1
    return out


def rrf(rankings: list[list[Hit]], k_rrf: int = 60) -> list[Hit]:
    scores: dict[str, float] = {}
    best: dict[str, Hit] = {}
    for ranking in rankings:
        for rank, h in enumerate(ranking):
            cid = h.chunk.chunk_id
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k_rrf + rank + 1)
            best.setdefault(cid, h)
    ordered = sorted(scores, key=lambda c: -scores[c])
    return [Hit(best[c].chunk, scores[c], best[c].requirement, "rrf") for c in ordered]


def expand_query(req: str) -> str:
    """Corrective re-query: add the vocabulary's names and implied phrasings for detected skills."""
    extra = []
    for sid in tag_skills(req):
        extra += SKILLS[sid]["names"] + SKILLS[sid]["implied"]
    low = req.lower()
    for sid, v in SKILLS.items():   # implied -> named (requirements phrased like case studies)
        if any(p.lower()[:30] in low for p in v["implied"]):
            extra += v["names"]
    return req + (" | " + " ; ".join(dict.fromkeys(extra)) if extra else "")


class Variant:
    name = "base"

    def __init__(self, store):
        self.store = store   # rag.retriever.PortfolioStore

    def retrieve(self, q: RetrievalQuery, k: int = 10) -> RetrievalResult:  # pragma: no cover
        raise NotImplementedError

    def reqs(self, q: RetrievalQuery) -> list[str]:
        return q.requirements or rule_requirements(q.job_text)
