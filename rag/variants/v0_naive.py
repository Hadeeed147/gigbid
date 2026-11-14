"""V0 (baseline, required): fixed-size chunks, top-k cosine on the whole job post."""
from rag.variants.base import EVIDENCE_TYPES, RetrievalQuery, RetrievalResult, Variant, dedupe_by_item


class V0Naive(Variant):
    name = "v0_naive"

    def retrieve(self, q: RetrievalQuery, k: int = 10) -> RetrievalResult:
        idx = self.store.fixed(q.tenant)
        hits = dedupe_by_item(idx.dense(q.job_text, k * 4, types=EVIDENCE_TYPES))[:k]
        return RetrievalResult(hits=hits, per_requirement={"(whole post)": hits})
