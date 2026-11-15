"""Retriever factory: the variant is chosen by config (rag.variant), and the
deployed choice is justified by evals (docs/adr/0003-rag-variant.md)."""
from __future__ import annotations

import json
import threading
from functools import lru_cache

from common.config import ROOT, cfg, env
from rag.index.stores import TenantIndex
from rag.ingest.chunkers import fixed_chunks, structured_chunks
from rag.ingest.loaders import RawItem, load_persona_dir
from rag.types import Chunk
from rag.variants.base import RetrievalQuery, RetrievalResult
from rag.variants.lite_bm25 import LiteBM25
from rag.variants.v0_naive import V0Naive
from rag.variants.v1_decompose import V1Decompose
from rag.variants.v2_hybrid import V2Hybrid
from rag.variants.v3_rerank import V3Rerank
from rag.variants.v4_outcome import V4Outcome
from rag.variants.v8_corrective import V8Corrective

VARIANTS = {cls.name: cls for cls in (V0Naive, V1Decompose, V2Hybrid, V3Rerank, V4Outcome, V8Corrective,
                                       LiteBM25)}
PERSONAS_DIR = ROOT / "data" / "personas"
USERS_DIR = ROOT / "data" / "processed" / "users"


class PortfolioStore:
    """Holds per-tenant indexes. Tenants are persona ids or user ids."""

    def __init__(self):
        self._lock = threading.RLock()
        self._items: dict[str, list[RawItem]] = {}
        self._structured: dict[str, TenantIndex] = {}
        self._fixed: dict[str, TenantIndex] = {}

    def tenant_dir(self, tenant: str):
        p = PERSONAS_DIR / tenant
        return p if p.exists() else USERS_DIR / tenant

    def items(self, tenant: str) -> list[RawItem]:
        with self._lock:
            if tenant not in self._items:
                d = self.tenant_dir(tenant)
                self._items[tenant] = load_persona_dir(d, tenant) if d.exists() else []
            return self._items[tenant]

    def structured(self, tenant: str) -> TenantIndex:
        with self._lock:
            if tenant not in self._structured:
                size = cfg("rag.chunk_size", 700)
                chunks = [c for it in self.items(tenant) for c in structured_chunks(it, size)]
                self._structured[tenant] = TenantIndex(tenant, chunks)
            return self._structured[tenant]

    def fixed(self, tenant: str) -> TenantIndex:
        with self._lock:
            if tenant not in self._fixed:
                chunks = [c for it in self.items(tenant) for c in fixed_chunks(it)]
                self._fixed[tenant] = TenantIndex(tenant, chunks)
            return self._fixed[tenant]

    def proposals(self, tenant: str) -> list[dict]:
        return [{"id": it.item_id, "text": it.text, "outcome": it.outcome, **it.extra}
                for it in self.items(tenant) if it.type == "proposal"]

    def chunk_by_item(self, tenant: str, item_id: str) -> list[Chunk]:
        return [c for c in self.structured(tenant).chunks if c.item_id == item_id]

    def get_item(self, tenant: str, item_id: str) -> RawItem | None:
        return next((it for it in self.items(tenant) if it.item_id == item_id), None)

    def add_item(self, item: RawItem) -> int:
        """Incremental re-indexing when the user adds work in the UI."""
        with self._lock:
            items = [i for i in self.items(item.tenant) if i.item_id != item.item_id] + [item]
            self._items[item.tenant] = items
            new = structured_chunks(item, cfg("rag.chunk_size", 700))
            self.structured(item.tenant).add(new)
            self._fixed.pop(item.tenant, None)
            self._persist_user_item(item)
            return len(new)

    def remove_item(self, tenant: str, item_id: str) -> int:
        with self._lock:
            self._items[tenant] = [i for i in self.items(tenant) if i.item_id != item_id]
            self._fixed.pop(tenant, None)
            return self.structured(tenant).remove_item(item_id)

    def _persist_user_item(self, item: RawItem) -> None:
        if (PERSONAS_DIR / item.tenant).exists():
            return
        d = USERS_DIR / item.tenant / "case_studies"
        d.mkdir(parents=True, exist_ok=True)
        meta = {"id": item.item_id, "project_id": item.project_id, "type": item.type, "source": "user",
                "date": item.date}
        (d / f"{item.item_id.split(':')[-1]}.md").write_text("---\n" + json.dumps(meta) + "\n---\n" + item.text,
                                                            encoding="utf-8")


def lite_mode() -> bool:
    """GIGBID_LITE=1 on the 512 MB public host: no embedding/reranker model is ever loaded."""
    return env("GIGBID_LITE", "") == "1"


@lru_cache(maxsize=1)
def get_store() -> PortfolioStore:
    return PortfolioStore()


def get_variant(name: str | None = None):
    name = name or ("lite_bm25" if lite_mode() else cfg("rag.variant", "v8_corrective"))
    return VARIANTS[name](get_store())


def search(tenant: str, job_text: str, requirements: list[str] | None = None, k: int | None = None,
           variant: str | None = None, category: str = "") -> RetrievalResult:
    v = get_variant(variant)
    return v.retrieve(RetrievalQuery(tenant=tenant, job_text=job_text, requirements=requirements or [],
                                     category=category), k or cfg("rag.k", 6))
