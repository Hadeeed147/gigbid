"""Arq worker settings. Run:  uv run arq worker.main.WorkerSettings

Schedules: every minute the worker checks which saved searches are due (each
search has its own interval, never below the per-mode floor in config: 10 min in
GigSim, 240 min in live mode; see docs/RUNBOOK.md), syncs marketplace events
into the pipeline board, and probes marketplace health.
"""
from __future__ import annotations

from contextlib import AsyncExitStack

from arq import cron
from arq.connections import RedisSettings

from agent.mcp_client import get_hub
from agent.runtime import runtime
from common.config import env
from worker import tasks


async def startup(ctx) -> None:
    stack = AsyncExitStack()
    ctx["stack"] = stack
    ctx["graphs"] = await stack.enter_async_context(runtime("auto"))
    await get_hub()


async def shutdown(ctx) -> None:
    await ctx["stack"].aclose()


class WorkerSettings:
    functions = [tasks.analyse_job, tasks.resume_bid, tasks.retry_thread, tasks.scout_user, tasks.sync_pipeline,
                 tasks.run_conversation, tasks.resume_conversation, tasks.health_check, tasks.ingest_github]
    cron_jobs = [cron(tasks.scout_all, minute=set(range(60)), run_at_startup=False, unique=True),
                 cron(tasks.sync_all, minute=set(range(60)), unique=True),
                 cron(tasks.health_check, minute=set(range(0, 60, 2)), unique=True)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(env("REDIS_URL", "redis://localhost:6379/0"))
    max_jobs = 4
    job_timeout = 900
    keep_result = 3600
    allow_abort_jobs = True
