"""Shared request dependencies: graphs (read-only use in the API), Arq pool, trace id."""
from __future__ import annotations

from fastapi import Request


def graphs(request: Request):
    return request.app.state.graphs


def arq(request: Request):
    return request.app.state.arq


def trace_id(request: Request) -> str:
    return request.state.trace_id


def iso(v) -> str | None:
    return v.isoformat() if v is not None and hasattr(v, "isoformat") else v


# Interactive work (approvals, "draft anyway") jumps ahead of background scouting:
# Arq orders its queue by scheduled time, so a time in the past puts a job first.
from datetime import datetime, timezone  # noqa: E402

PRIORITY = {"_defer_until": datetime(2020, 1, 1, tzinfo=timezone.utc)}
