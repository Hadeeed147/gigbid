"""Shared eval helpers: dev-set loading, gold evidence, metric functions, result writing."""
from __future__ import annotations

import json
import math
import platform
import subprocess
import time
from pathlib import Path

from common.config import ROOT, cfg, load_config

DATASETS = ROOT / "evals" / "datasets"
RESULTS = ROOT / "evals" / "results"
PERSONAS = ("ai_ml", "fullstack", "data_analyst")
EVIDENCE_TYPES = {"case_study", "readme", "code", "review"}


def load_dev(persona: str, limit: int | None = None, kinds: set[str] | None = None, seed_every: int = 1) -> list[dict]:
    rows = [json.loads(x) for x in (DATASETS / f"dev_{persona}.jsonl").read_text(encoding="utf-8").splitlines() if x]
    if kinds:
        rows = [r for r in rows if r["gold"]["kind"] in kinds]
    rows = rows[::seed_every]
    return rows[:limit] if limit else rows


def public(job: dict) -> dict:
    return {k: v for k, v in job.items() if k not in ("gold", "_hidden")}


def gold_items(job: dict, store, persona: str) -> tuple[dict[str, float], set[str]]:
    """item_id -> graded relevance, plus the 'strong' set (items of the best-matching projects)."""
    grades = job["gold"]["relevant_projects"]
    if not grades:
        return {}, set()
    top = max(grades.values())
    strong_projects = {p for p, g in grades.items() if g >= max(1.0, top - 0.3)}
    rel, strong = {}, set()
    for it in store.items(persona):
        if it.type in EVIDENCE_TYPES and it.project_id in grades:
            rel[it.item_id] = grades[it.project_id]
            if it.project_id in strong_projects:
                strong.add(it.item_id)
    return rel, strong


def recall_at_k(ranked: list[str], strong: set[str], k: int = 5) -> float:
    if not strong:
        return float("nan")
    return len(set(ranked[:k]) & strong) / min(k, len(strong))


def mrr(ranked: list[str], strong: set[str]) -> float:
    for i, r in enumerate(ranked):
        if r in strong:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(ranked: list[str], rel: dict[str, float], k: int = 10) -> float:
    dcg = sum(rel.get(r, 0.0) / math.log2(i + 2) for i, r in enumerate(ranked[:k]))
    ideal = sorted(rel.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else float("nan")


def pctl(xs: list[float], q: float) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    i = min(len(xs) - 1, max(0, math.ceil(q * len(xs)) - 1))
    return round(xs[i], 3)


def mean(xs) -> float | None:
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return round(sum(xs) / len(xs), 4) if xs else None


def provenance(extra: dict | None = None) -> dict:
    """Every results file records how it was produced, so each number is traceable."""
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        commit = "unknown"
    conf = load_config()
    prof = conf["active_profile"]
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "git_commit": commit, "profile": prof,
            "models": conf["profiles"].get(prof), "embeddings": cfg("embeddings.model"),
            "reranker": cfg("reranker.model"), "machine": f"{platform.system()} {platform.machine()}",
            "fake_llm": __import__("os").environ.get("GIGBID_FAKE_LLM") == "1", **(extra or {})}


def write_results(name: str, payload: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / f"{name}.json"
    p.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    return p
