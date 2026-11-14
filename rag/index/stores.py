"""Tenant-scoped indexes: dense (numpy in memory, or pgvector) and BM25.

The same `TenantIndex` serves evals (memory backend) and the deployed app
(pgvector backend, so a user's newly added work is re-indexed incrementally and
survives restarts). Every search is scoped to one tenant (E4).
"""
from __future__ import annotations

import json
import re

import numpy as np
from rank_bm25 import BM25Okapi

from rag.index.embed import embed
from rag.types import Chunk, Hit

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")


def tokenize(text: str) -> list[str]:
    return [t.strip(".") for t in _TOKEN.findall(text.lower())]


class TenantIndex:
    def __init__(self, tenant: str, chunks: list[Chunk]):
        self.tenant = tenant
        self.chunks = [c for c in chunks if c.tenant == tenant]
        self._vecs: np.ndarray | None = None
        self._bm25: BM25Okapi | None = None

    # ---- dense -------------------------------------------------------------
    def _text_for_embedding(self, c: Chunk) -> str:
        return (c.context + "\n" + c.text) if c.context else c.text

    @property
    def vecs(self) -> np.ndarray:
        if self._vecs is None:
            self._vecs = embed([self._text_for_embedding(c) for c in self.chunks], kind="doc")
        return self._vecs

    def dense(self, query: str, k: int, types: set[str] | None = None) -> list[Hit]:
        if not self.chunks:
            return []
        q = embed([query], kind="query")[0]
        sims = self.vecs @ q
        order = np.argsort(-sims)
        out = []
        for i in order:
            c = self.chunks[i]
            if types and c.type not in types:
                continue
            out.append(Hit(c, float(sims[i]), retriever="dense"))
            if len(out) >= k:
                break
        return out

    # ---- sparse ------------------------------------------------------------
    @property
    def bm25(self) -> BM25Okapi:
        if self._bm25 is None:
            self._bm25 = BM25Okapi([tokenize(c.title + " " + c.text) for c in self.chunks])
        return self._bm25

    def sparse(self, query: str, k: int, types: set[str] | None = None) -> list[Hit]:
        if not self.chunks:
            return []
        scores = self.bm25.get_scores(tokenize(query))
        order = np.argsort(-scores)
        out = []
        for i in order:
            if scores[i] <= 0:
                break
            c = self.chunks[i]
            if types and c.type not in types:
                continue
            out.append(Hit(c, float(scores[i]), retriever="bm25"))
            if len(out) >= k:
                break
        return out

    def add(self, new: list[Chunk]) -> None:
        """Incremental re-index: append and embed only the new chunks."""
        new = [c for c in new if c.tenant == self.tenant]
        if not new:
            return
        ids = {c.chunk_id for c in new}
        keep = [i for i, c in enumerate(self.chunks) if c.chunk_id not in ids]
        new_vecs = embed([self._text_for_embedding(c) for c in new], kind="doc")
        old = self.vecs[keep] if self._vecs is not None else None
        self.chunks = [self.chunks[i] for i in keep] + new
        self._vecs = new_vecs if old is None else np.vstack([old, new_vecs])
        self._bm25 = None

    def remove_item(self, item_id: str) -> int:
        keep = [i for i, c in enumerate(self.chunks) if c.item_id != item_id]
        removed = len(self.chunks) - len(keep)
        if removed:
            if self._vecs is not None:
                self._vecs = self._vecs[keep]
            self.chunks = [self.chunks[i] for i in keep]
            self._bm25 = None
        return removed


# ---------------------------------------------------------------------------
# pgvector persistence (deployed app)
# ---------------------------------------------------------------------------
PG_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS evidence_chunks (
  chunk_id TEXT PRIMARY KEY,
  tenant TEXT NOT NULL,
  item_id TEXT NOT NULL,
  payload JSONB NOT NULL,
  embedding vector(%d)
);
CREATE INDEX IF NOT EXISTS evidence_chunks_tenant ON evidence_chunks (tenant);
"""


def pg_save(conn, chunks: list[Chunk], vecs: np.ndarray) -> None:
    from pgvector.psycopg import register_vector
    register_vector(conn)
    with conn.cursor() as cur:
        for c, v in zip(chunks, vecs, strict=True):
            cur.execute(
                "INSERT INTO evidence_chunks (chunk_id, tenant, item_id, payload, embedding) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (chunk_id) DO UPDATE SET payload=excluded.payload, embedding=excluded.embedding",
                (c.chunk_id, c.tenant, c.item_id, json.dumps(c.to_dict()), v))
    conn.commit()


def pg_load(conn, tenant: str) -> tuple[list[Chunk], np.ndarray]:
    from pgvector.psycopg import register_vector
    register_vector(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT payload, embedding FROM evidence_chunks WHERE tenant=%s ORDER BY chunk_id", (tenant,))
        rows = cur.fetchall()
    chunks = [Chunk(**(r[0] if isinstance(r[0], dict) else json.loads(r[0]))) for r in rows]
    vecs = np.array([r[1] for r in rows], dtype=np.float32) if rows else np.zeros((0, 384), dtype=np.float32)
    return chunks, vecs


def pg_delete_item(conn, tenant: str, item_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evidence_chunks WHERE tenant=%s AND item_id=%s", (tenant, item_id))
        n = cur.rowcount
    conn.commit()
    return n
