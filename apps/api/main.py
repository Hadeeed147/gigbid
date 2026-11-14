"""GigBid API (FastAPI). Run:  uv run uvicorn apps.api.main:app --port 8000"""
from __future__ import annotations

import uuid
from contextlib import AsyncExitStack, asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agent.runtime import runtime
from apps.api import db
from apps.api.routers import auth, jobs, messages, proposals, settings
from apps.api import streaming
from common.config import env
from common.pii import mask_text


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.pool()
    async with AsyncExitStack() as stack:
        app.state.graphs = await stack.enter_async_context(runtime("auto"))
        app.state.arq = await create_pool(RedisSettings.from_dsn(env("REDIS_URL", "redis://localhost:6379/0")))
        yield
        await app.state.arq.aclose()


app = FastAPI(title="GigBid API", version="1.0.0", lifespan=lifespan,
              description="Multi-agent freelancer copilot. Every proposal and message waits for human approval.")
app.add_middleware(CORSMiddleware, allow_origins=[o for o in (env("WEB_PUBLIC_URL", ""), "http://localhost:5173",
                                                              "http://127.0.0.1:5173") if o],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Trace-Id"])


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    """One trace id per UI request; forwarded to the worker, graph, MCP servers and audit log."""
    tid = request.headers.get("x-trace-id") or uuid.uuid4().hex
    request.state.trace_id = tid
    try:
        resp = await call_next(request)
    except Exception as e:  # noqa: BLE001 - never leak PII in error bodies
        resp = JSONResponse({"detail": mask_text(str(e))[:300]}, status_code=500)
    resp.headers["X-Trace-Id"] = tid
    return resp


for r in (auth.router, jobs.router, proposals.router, messages.router, settings.router, streaming.router):
    app.include_router(r, prefix="/api")
