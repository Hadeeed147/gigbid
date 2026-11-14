"""Scout: run saved searches, de-duplicate, queue new jobs; and the bid graph's intake node."""
from __future__ import annotations

import hashlib
import re

from agent.mcp_client import get_hub
from agent.nodes._runtime import node


def fingerprint(job: dict) -> str:
    """Duplicate detection across reposts: normalised title + client + budget."""
    title = re.sub(r"\(reposted\)|\b(needed|wanted|required|urgent)\b", "", job.get("title", "").lower())
    title = re.sub(r"[^a-z0-9 ]", "", title)
    title = " ".join(sorted(set(title.split())))
    b = job.get("budget") or {}
    return hashlib.sha1(f"{job.get('client_id')}|{title}|{b.get('amount') or b.get('max')}".encode()).hexdigest()[:16]


async def run_saved_search(search: dict, seen_ids: set[str], seen_fps: set[str], limit: int = 25) -> list[dict]:
    """Returns new, non-duplicate jobs; caller persists seen sets (idempotent scouting)."""
    hub = await get_hub()
    res = await hub.call("scout", "search_jobs", {"query": search.get("query", ""),
                                                  "category": search.get("category", ""), "limit": limit})
    fresh = []
    for job in res.get("jobs", []):
        fp = fingerprint(job)
        if job["id"] in seen_ids:
            continue
        seen_ids.add(job["id"])
        if fp in seen_fps:
            job["_duplicate"] = True
        seen_fps.add(fp)
        fresh.append(job)
    return fresh


@node("intake")
async def intake(state: dict) -> dict:
    """Scout hands a job in: load the full post (if only the id was queued)."""
    job = state.get("job") or {}
    if not job.get("description"):
        hub = await get_hub()
        job = await hub.call("scout", "get_job", {"job_id": state["job_id"]})
    return {"job": job, "status": "analysing", "revision": 0}
