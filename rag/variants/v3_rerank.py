"""V3 (retrieval, required): cross-encoder reranking of the V2 candidates,
per requirement, for precision at small k."""
from common.config import cfg
from rag.index.embed import rerank, sigmoid
from rag.types import Hit
from rag.variants.base import RetrievalQuery, RetrievalResult, round_robin
from rag.variants.v2_hybrid import V2Hybrid


class V3Rerank(V2Hybrid):
    name = "v3_rerank"
    depth = 30

    def reranked(self, tenant: str, req: str) -> list[Hit]:
        cands = self.candidates(tenant, req)[: cfg("rag.rerank_candidates", 30)]
        scores = rerank(req, [h.chunk.title + "\n" + h.chunk.text for h in cands])
        out = [Hit(h.chunk, sigmoid(s), req, "cross_encoder") for h, s in zip(cands, scores, strict=True)]
        return sorted(out, key=lambda h: -h.score)

    def retrieve(self, q: RetrievalQuery, k: int = 10) -> RetrievalResult:
        per_req = {r: self.reranked(q.tenant, r)[: k * 2] for r in self.reqs(q)}
        return RetrievalResult(hits=round_robin(per_req, k), per_requirement=per_req)
