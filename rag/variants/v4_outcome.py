"""V4 (ranking): outcome-aware ranking. Projects cited in past proposals that
WON or got REPLIES on similar jobs get a boost; ignored ones a small penalty.
Also returns the best-performing similar proposals as phrasing exemplars."""
from common.config import cfg
from rag.ingest.loaders import tag_skills
from rag.types import Hit
from rag.variants.base import RetrievalQuery, RetrievalResult, round_robin
from rag.variants.v3_rerank import V3Rerank


class V4Outcome(V3Rerank):
    name = "v4_outcome"

    def outcome_prior(self, tenant: str, q: RetrievalQuery, reqs: list[str]) -> tuple[dict[str, float], list[dict]]:
        boosts = cfg("rag.outcome_boost")
        want = set(tag_skills(q.job_text + " " + " ".join(reqs)))
        prior: dict[str, float] = {}
        scored = []
        for p in self.store.proposals(tenant):
            overlap = len(want & set(p.get("job_skills", []))) / (len(want) or 1)
            if q.category and p.get("job_category") == q.category:
                overlap += 0.2
            if overlap <= 0:
                continue
            w = boosts.get(p.get("outcome", "ignored"), 0.0) * min(1.0, overlap)
            for pid in p.get("cited_projects", []):
                prior[pid] = prior.get(pid, 0.0) + w
            scored.append((overlap + (0.5 if p.get("outcome") == "won" else 0.25 if p.get("outcome") == "replied" else 0), p))
        # clip so a single prolific project cannot dominate
        prior = {k: max(-0.1, min(0.3, v)) for k, v in prior.items()}
        exemplars = [p for _, p in sorted(scored, key=lambda x: -x[0]) if p.get("outcome") in ("won", "replied")][:3]
        return prior, exemplars

    def retrieve(self, q: RetrievalQuery, k: int = 10) -> RetrievalResult:
        reqs = self.reqs(q)
        prior, exemplars = self.outcome_prior(q.tenant, q, reqs)
        per_req = {}
        for r in reqs:
            hits = [Hit(h.chunk, h.score + prior.get(h.chunk.project_id or "", 0.0), r, "outcome_aware")
                    for h in self.reranked(q.tenant, r)]
            per_req[r] = sorted(hits, key=lambda h: -h.score)[: k * 2]
        return RetrievalResult(hits=round_robin(per_req, k), per_requirement=per_req,
                               exemplars=[{"id": e["id"], "text": e["text"], "outcome": e["outcome"]} for e in exemplars])
