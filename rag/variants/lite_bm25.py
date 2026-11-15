"""Lite (deployment-only): requirement decomposition + BM25 keyword retrieval.

Exists for one reason: the free public host has 512 MB RAM, and the embedding +
reranker models alone need well over that. This variant never loads a model, so
the public demo link can run on that host. It is NOT the variant the evaluation
chose (V8 corrective); docker compose, the evals and the viva demo run the full
system. Its cost in retrieval quality is measured on the same dev set
(evals/results/rag_eval_lite.csv) and reported, not assumed.
"""
from rag.variants.base import (
    EVIDENCE_TYPES,
    RetrievalQuery,
    RetrievalResult,
    Variant,
    dedupe_by_item,
    round_robin,
)


class LiteBM25(Variant):
    name = "lite_bm25"

    def retrieve(self, q: RetrievalQuery, k: int = 10) -> RetrievalResult:
        idx = self.store.structured(q.tenant)
        per_req = {}
        for r in self.reqs(q):
            hits = dedupe_by_item(idx.sparse(r, k * 2, types=EVIDENCE_TYPES))
            for h in hits:
                h.requirement = r
            per_req[r] = hits
        return RetrievalResult(hits=round_robin(per_req, k), per_requirement=per_req)
