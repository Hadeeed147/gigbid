"""Open embedding + reranker models on CPU (fastembed / ONNX). Cached on disk."""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import numpy as np

from common.config import ROOT, cfg

CACHE = ROOT / "data" / "processed" / "emb_cache"


@lru_cache(maxsize=1)
def _embedder():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=cfg("embeddings.model"))


@lru_cache(maxsize=1)
def _reranker():
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    return TextCrossEncoder(model_name=cfg("reranker.model"))


def _key(texts: list[str], kind: str) -> Path:
    h = hashlib.sha256((kind + cfg("embeddings.model") + "\x00".join(texts)).encode()).hexdigest()[:24]
    return CACHE / f"{kind}_{h}.npy"


def embed(texts: list[str], kind: str = "doc") -> np.ndarray:
    """L2-normalised embeddings. BGE wants a query instruction prefix for queries."""
    if not texts:
        return np.zeros((0, cfg("embeddings.dim")), dtype=np.float32)
    path = _key(texts, kind)
    if path.exists():
        return np.load(path)
    model = _embedder()
    inp = texts
    if kind == "query" and "bge" in cfg("embeddings.model").lower():
        inp = ["Represent this sentence for searching relevant passages: " + t for t in texts]
    vecs = np.array(list(model.embed(inp)), dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    CACHE.mkdir(parents=True, exist_ok=True)
    if len(texts) > 4:  # cache document batches; queries are cheap
        np.save(path, vecs)
    return vecs


def rerank(query: str, docs: list[str]) -> list[float]:
    if not docs:
        return []
    return [float(s) for s in _reranker().rerank(query, docs)]


def sigmoid(x: float) -> float:
    return float(1 / (1 + np.exp(-x)))
