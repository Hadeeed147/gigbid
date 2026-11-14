"""Shared MCP server plumbing: bearer auth, caller identity + trace id,
per-user rate limiting and an append-only audit log."""
from __future__ import annotations

import json
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context

from common.config import ROOT, cfg, env
from common.pii import mask

AUDIT_DIR = ROOT / "data" / "processed" / "audit"


class StaticTokenVerifier(TokenVerifier):
    """Accepts the shared service token presented by the GigBid agent (MCP_BEARER_TOKEN)."""

    async def verify_token(self, token: str) -> AccessToken | None:
        expected = env("MCP_BEARER_TOKEN")
        if expected and token == expected:
            return AccessToken(token=token, client_id="gigbid-agent", scopes=["gigbid"], expires_at=None)
        return None


def auth_kwargs(port: int) -> dict:
    """FastMCP kwargs that enable bearer auth on the HTTP endpoint (skipped if no token is configured)."""
    if not env("MCP_BEARER_TOKEN"):
        return {}
    base = f"http://localhost:{port}"
    return {"token_verifier": StaticTokenVerifier(),
            "auth": AuthSettings(issuer_url=base, resource_server_url=base, required_scopes=["gigbid"])}


def identity(ctx: Context | None) -> tuple[str, str]:
    """(user_id, trace_id) from request headers set by the agent's tool interceptor."""
    user, trace = "anonymous", ""
    try:
        req = ctx.request_context.request if ctx else None
        if req is not None:
            user = req.headers.get("x-gigbid-user", user)
            trace = req.headers.get("x-trace-id", "")
    except (AttributeError, LookupError, ValueError):
        pass
    from mcp_servers import local_identity
    if user == "anonymous" and local_identity.get():
        user, trace = local_identity.get()
    return user, trace or uuid.uuid4().hex


class RateLimiter:
    """Sliding-window limiter per user, set below GigSim's own limit (polite by default)."""

    def __init__(self, per_minute: int | None = None):
        self.per_minute = per_minute or cfg("marketplace.rate_limit_per_minute", 50)
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def wait(self, user: str) -> float:
        """Block until a slot is free; returns seconds waited."""
        waited = 0.0
        while True:
            with self._lock:
                q = self._hits[user]
                now = time.time()
                while q and now - q[0] > 60:
                    q.popleft()
                if len(q) < self.per_minute:
                    q.append(now)
                    return waited
                sleep_for = 60 - (now - q[0]) + 0.05
            time.sleep(sleep_for)
            waited += sleep_for


class AuditLog:
    """Append-only JSONL (one file per server). Arguments and results are PII-masked."""

    def __init__(self, server: str):
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        self.path: Path = AUDIT_DIR / f"{server}.jsonl"
        self._lock = threading.Lock()

    def write(self, *, user: str, tool: str, args: dict, result: Any, trace_id: str, ok: bool = True) -> None:
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "user": user, "tool": tool, "args": mask(args),
               "result": mask(result if len(json.dumps(result, default=str)) < 4000 else {"truncated": True}),
               "trace_id": trace_id, "ok": ok}
        line = json.dumps(rec, default=str)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def tail(self, n: int = 50) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines()[-n:]]
