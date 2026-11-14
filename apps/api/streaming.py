"""SSE bridge to LangGraph streams. The worker streams the graph with
stream_mode=["updates","custom"] and publishes each node update to Redis; this
endpoint replays the run so far, then relays live events. Reconnecting after a
refresh replays history, so the user never stares at an empty spinner."""
from __future__ import annotations

import asyncio
import json

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from apps.api import db
from apps.api.auth.security import current_user
from apps.api.deps import iso
from apps.api.schemas.models import RunDetail, RunOut
from common.config import env
from worker.events import history

router = APIRouter(tags=["runs"])


def _owns(user_id: str, thread_id: str) -> None:
    if not (thread_id.startswith(f"bid:{user_id}:") or thread_id.startswith(f"conv:{user_id}:")
            or thread_id == f"pipeline:{user_id}"):
        raise HTTPException(404, "run not found")


@router.get("/runs", response_model=list[RunOut])
def runs(user: dict = Depends(current_user), thread_id: str | None = None, limit: int = 50) -> list[RunOut]:
    sql, p = "SELECT * FROM runs WHERE user_id=%s", [user["id"]]
    if thread_id:
        sql += " AND thread_id=%s"
        p.append(thread_id)
    rows = db.q(sql + " ORDER BY started_at DESC LIMIT %s", (*p, limit))
    return [RunOut(**{**{k: r.get(k) for k in RunOut.model_fields}, "started_at": iso(r["started_at"]),
                      "finished_at": iso(r["finished_at"])}) for r in rows]


@router.get("/runs/thread/{thread_id:path}", response_model=RunDetail)
def run_detail(thread_id: str, user: dict = Depends(current_user)) -> RunDetail:
    _owns(user["id"], thread_id)
    r = db.one("SELECT * FROM runs WHERE user_id=%s AND thread_id=%s ORDER BY started_at DESC LIMIT 1",
               (user["id"], thread_id))
    run = RunOut(**{**{k: r.get(k) for k in RunOut.model_fields}, "started_at": iso(r["started_at"]),
                    "finished_at": iso(r["finished_at"])}) if r else None
    return RunDetail(run=run, events=history(thread_id))


@router.get("/runs/stream/{thread_id:path}")
async def stream(thread_id: str, request: Request, token: str = ""):
    """SSE. EventSource cannot send headers, so the session token comes as ?token=."""
    from fastapi.security import HTTPAuthorizationCredentials
    user = current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
    _owns(user["id"], thread_id)

    async def gen():
        for ev in history(thread_id):
            yield {"event": "message", "data": json.dumps(ev)}
        r = aioredis.from_url(env("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
        ps = r.pubsub()
        await ps.subscribe(f"chan:{thread_id}")
        try:
            while not await request.is_disconnected():
                msg = await ps.get_message(ignore_subscribe_messages=True, timeout=15)
                if msg:
                    yield {"event": "message", "data": msg["data"]}
                else:
                    yield {"event": "ping", "data": "{}"}
                await asyncio.sleep(0)
        finally:
            await ps.unsubscribe()
            await r.aclose()
    return EventSourceResponse(gen())
