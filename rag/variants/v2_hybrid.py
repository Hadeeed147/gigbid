"""V2 (retrieval, required): hybrid BM25 + dense with reciprocal rank fusion,
per requirement. BM25 catches exact tool names ("Celery", "dbt") that embeddings blur."""
from common.config import cfg
from rag.variants.base import (EVIDENCE_TYPES, RetrievalQuery, RetrievalResult, Variant, dedupe_by_item, round_robin,
                               rrf)


class V2Hybrid(Variant):
    name = "v2_hybrid"
    depth = 20

    def candidates(self, tenant: str, req: str) -> list:
        idx = self.store.structured(tenant)
        fused = rrf([idx.dense(req, self.depth, EVIDENCE_TYPES), idx.sparse(req, self.depth, EVIDENCE_TYPES)],
                    cfg("rag.rrf_k", 60))
        for h in fused:
            h.requirement = req
        return dedupe_by_item(fused)

    def retrieve(self, q: RetrievalQuery, k: int = 10) -> RetrievalResult:
        per_req = {r: self.candidates(q.tenant, r)[: k * 2] for r in self.reqs(q)}
        return RetrievalResult(hits=round_robin(per_req, k), per_requirement=per_req)
