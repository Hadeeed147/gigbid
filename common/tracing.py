"""LangSmith tracing with PII masking (E3/E4).

One trace id flows UI -> API -> worker -> graph -> every MCP server -> audit log:
the API mints it (or accepts X-Trace-Id from the UI), it is stored in graph state,
sent as X-Trace-Id on every MCP call, written to the audit log, and attached to the
LangSmith root run as metadata (and used as the root run id, so the trace URL is known).
Emails, phone numbers, card numbers and payment handles are masked before upload.
"""
from __future__ import annotations

from functools import lru_cache

from common.config import env
from common.pii import mask_text


def enabled() -> bool:
    return bool(env("LANGSMITH_API_KEY")) and (env("LANGSMITH_TRACING", "true") or "").lower() == "true"


@lru_cache(maxsize=1)
def _client():
    from langsmith import Client
    from langsmith.anonymizer import create_anonymizer

    def scrub(value, path):  # noqa: ARG001 - langsmith anonymizer signature
        return mask_text(value) if isinstance(value, str) else value
    return Client(anonymizer=create_anonymizer(scrub))


def callbacks() -> list:
    if not enabled():
        return []
    from langchain_core.tracers import LangChainTracer
    return [LangChainTracer(client=_client(), project_name=env("LANGSMITH_PROJECT", "gigbid"))]


def trace_url(run_id: str) -> str | None:
    if not enabled():
        return None
    try:
        run = _client().read_run(run_id)
        return _client().get_run_url(run=run)
    except Exception:
        return None
