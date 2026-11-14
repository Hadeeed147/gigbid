"""V1 (query, required): requirement decomposition. One dense retrieval per
extracted requirement over structure-aware chunks, merged round-robin."""
from rag.variants.base import (EVIDENCE_TYPES, RetrievalQuery, RetrievalResult, Variant, dedupe_by_item,
                               round_robin)


class V1Decompose(Variant):
    name = "v1_decompose"

    def retrieve(self, q: RetrievalQuery, k: int = 10) -> RetrievalResult:
        idx = self.store.structured(q.tenant)
        per_req = {}
        for r in self.reqs(q):
            hits = dedupe_by_item(idx.dense(r, k * 2, types=EVIDENCE_TYPES))
            for h in hits:
                h.requirement = r
            per_req[r] = hits
        return RetrievalResult(hits=round_robin(per_req, k), per_requirement=per_req)
