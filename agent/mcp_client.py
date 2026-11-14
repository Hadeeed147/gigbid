"""MultiServerMCPClient setup + per-agent tool allowlists (A6).

Agents never touch GigSim, Upwork, the DB or files directly: every capability
is an MCP tool. Two transports, chosen by config `mcp.transport`:
  - http:      MultiServerMCPClient over Streamable HTTP (deployed system)
  - inprocess: in-memory MCP sessions to the same FastMCP servers (evals, tests)
Either way the agent sees the same LangChain tools, filtered by name per agent.

Identity + tracing: an interceptor stamps X-GigBid-User and X-Trace-Id on every
call (http); in-process calls carry them in a context variable. Each call is
appended to the thread's execution trace (tool, args, result, latency).
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import time
import uuid
from contextlib import AsyncExitStack
from typing import Any

from langchain_core.tools import BaseTool

from agent.marketplace_port import MarketplaceRejected, MarketplaceUnavailable
from common.config import cfg, env
from common.pii import mask

# ---------------------------------------------------------------------------
# Per-agent allowlists: each agent gets only the tools it needs (A6).
# ---------------------------------------------------------------------------
ALLOWLISTS: dict[str, set[str]] = {
    "scout": {"search_jobs", "get_job"},
    "analyst": set(),
    "risk": {"get_job", "get_client_history"},
    "matcher": {"search_evidence", "list_skills"},
    "pricing": {"get_market_stats", "get_client_history", "get_connects_balance", "get_policy"},
    "writer": {"search_evidence", "get_case_study"},
    "verifier": {"search_evidence"},
    "critic": {"search_evidence"},
    "compliance": set(),
    "approval": {"create_proposal_draft"},            # dry_run preview only
    "submit": {"create_proposal_draft", "submit_proposal", "get_connects_balance"},
    "liaison": {"list_threads", "list_messages", "free_slots", "create_email_draft", "search_evidence"},
    "send": {"send_message", "create_interview_hold"},
    "pipeline": {"list_events", "list_threads"},
    # baselines for R&D question C get everything
    "react_baseline": {"*"},
}

SERVERS = {
    "portfolio": ("PORTFOLIO_MCP_URL", "http://localhost:8201/mcp"),
    "marketplace": ("MARKETPLACE_MCP_URL", "http://localhost:8202/mcp"),
    "workspace": ("WORKSPACE_MCP_URL", "http://localhost:8203/mcp"),
}

# (user_id, trace_id) for the current run, and the execution trace collector.
run_identity: contextvars.ContextVar[tuple[str, str, str]] = contextvars.ContextVar(
    "run_identity", default=("anonymous", "", ""))
exec_trace: contextvars.ContextVar[list | None] = contextvars.ContextVar("exec_trace", default=None)


class ToolDenied(PermissionError):
    pass


async def _identity_interceptor(request, handler):
    user, trace, tenant = run_identity.get()
    headers = {**(request.headers or {}), "X-GigBid-User": user, "X-GigBid-Tenant": tenant or user,
               "X-Trace-Id": trace or uuid.uuid4().hex}
    return await handler(request.override(headers=headers))


class MCPHub:
    """Holds MCP connections and tools for the process. Use `await get_hub()`."""

    def __init__(self, transport: str | None = None):
        self.transport = transport or cfg("mcp.transport", "http")
        self.tools: dict[str, BaseTool] = {}
        self.tool_server: dict[str, str] = {}
        self._stack: AsyncExitStack | None = None
        self.github_tools: list[BaseTool] = []

    async def start(self) -> MCPHub:
        if self.transport == "inprocess":
            await self._start_inprocess()
        else:
            await self._start_http()
        return self

    async def _start_http(self) -> None:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        bearer = env("MCP_BEARER_TOKEN")
        conns = {name: {"transport": "streamable_http", "url": env(var, default),
                        "headers": {"Authorization": f"Bearer {bearer}"} if bearer else {},
                        "timeout": __import__("datetime").timedelta(seconds=cfg("node_runtime.timeout_s", 60))}
                 for name, (var, default) in SERVERS.items()}
        self.client = MultiServerMCPClient(conns, tool_interceptors=[_identity_interceptor])
        for name in SERVERS:
            try:
                for t in await self.client.get_tools(server_name=name):
                    self.tools[t.name] = t
                    self.tool_server[t.name] = name
            except Exception as e:  # a server being down must not stop the others (degraded mode)
                self.tool_server[f"__down__{name}"] = str(e)[:200]

    async def _start_inprocess(self) -> None:
        """In-memory sessions are opened per call (anyio scopes must open/close in one task)."""
        from mcp.shared.memory import create_connected_server_and_client_session

        from mcp_servers.marketplace.server import mcp as marketplace
        from mcp_servers.portfolio.server import mcp as portfolio
        from mcp_servers.workspace.server import mcp as workspace
        self._servers = {"portfolio": portfolio, "marketplace": marketplace, "workspace": workspace}
        self._meta: dict[str, Any] = {}
        for name, srv in self._servers.items():
            async with create_connected_server_and_client_session(srv._mcp_server) as s:
                for t in (await s.list_tools()).tools:
                    self._meta[t.name] = t
                    self.tool_server[t.name] = name
                    self.tools[t.name] = self._wrap(t)

    def _wrap(self, meta) -> BaseTool:
        """LangChain tool around an in-process MCP tool (used by the ReAct / supervisor baselines)."""
        from langchain_core.tools import StructuredTool
        hub = self

        async def _call(**kwargs):
            return json.dumps(await hub.call("react_baseline", meta.name, kwargs), default=str)
        return StructuredTool(name=meta.name, description=meta.description or "", args_schema=meta.inputSchema,
                              coroutine=_call)

    async def _call_inprocess(self, tool: str, args: dict) -> tuple[bool, str, Any]:
        from mcp.shared.memory import create_connected_server_and_client_session
        srv = self._servers[self.tool_server[tool]]
        async with create_connected_server_and_client_session(srv._mcp_server) as s:
            r = await s.call_tool(tool, args)
        text = "".join(getattr(c, "text", "") for c in r.content)
        return bool(r.isError), text, r.structuredContent

    async def close(self) -> None:
        if self._stack:
            await self._stack.aclose()

    def down_servers(self) -> list[str]:
        return [k.removeprefix("__down__") for k in self.tool_server if k.startswith("__down__")]

    def tools_for(self, agent: str) -> list[BaseTool]:
        allowed = ALLOWLISTS.get(agent, set())
        if "*" in allowed:
            return list(self.tools.values())
        return [t for n, t in self.tools.items() if n in allowed]

    async def call(self, agent: str, tool: str, args: dict[str, Any]) -> Any:
        """Call one tool on behalf of `agent`; returns structured content (dict) or text."""
        allowed = ALLOWLISTS.get(agent, set())
        if tool not in allowed and "*" not in allowed:
            raise ToolDenied(f"agent '{agent}' may not call '{tool}'")
        if tool not in self.tools:
            server = "marketplace" if tool in ALLOWLISTS["submit"] | ALLOWLISTS["scout"] | ALLOWLISTS["pricing"] else "?"
            raise MarketplaceUnavailable(f"tool '{tool}' unavailable (server {server} down)")
        user, trace, tenant = run_identity.get()
        from mcp_servers import local_identity
        tok = local_identity.set((user, trace, tenant or user))
        t0 = time.time()
        timeout = cfg("node_runtime.timeout_s", 60)
        try:
            if self.transport == "inprocess":
                is_err, text, structured = await asyncio.wait_for(self._call_inprocess(tool, args), timeout)
                msg = None
            else:
                msg = await asyncio.wait_for(
                    self.tools[tool].ainvoke({"type": "tool_call", "id": uuid.uuid4().hex, "name": tool, "args": args}),
                    timeout=timeout)
                text = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
                is_err = getattr(msg, "status", "success") == "error"
                artifact = getattr(msg, "artifact", None) or {}
                structured = artifact.get("structured_content") if isinstance(artifact, dict) else None
        except (TimeoutError, OSError, ConnectionError) as e:
            self._record(agent, tool, args, {"error": str(e)}, t0, ok=False)
            raise MarketplaceUnavailable(f"{tool}: {e}") from e
        finally:
            local_identity.reset(tok)
        if is_err:
            self._record(agent, tool, args, {"error": text[:300]}, t0, ok=False)
            if "marketplace_unavailable" in text or "Connection" in text:
                raise MarketplaceUnavailable(text[:300])
            if "marketplace_rejected" in text:
                raise MarketplaceRejected(400, text[:300])
            raise RuntimeError(f"{tool} failed: {text[:300]}")
        result = structured
        if result is None:
            try:
                result = json.loads(text) if isinstance(text, str) else text
                if isinstance(result, list) and result and isinstance(result[0], dict) and "text" in result[0]:
                    result = json.loads(result[0]["text"])
            except (json.JSONDecodeError, TypeError):
                result = text
        self._record(agent, tool, args, result, t0, ok=True)
        return result

    @staticmethod
    def _record(agent: str, tool: str, args: dict, result: Any, t0: float, ok: bool) -> None:
        tr = exec_trace.get()
        if tr is not None:
            preview = json.dumps(result, default=str)
            tr.append({"kind": "tool", "agent": agent, "tool": tool, "args": mask(args), "ok": ok,
                       "result": mask(json.loads(preview) if len(preview) < 3000 else {"preview": preview[:3000]}),
                       "latency_s": round(time.time() - t0, 3), "ts": time.time()})


_HUB: MCPHub | None = None
_HUB_LOCK = asyncio.Lock()


async def get_hub(transport: str | None = None) -> MCPHub:
    global _HUB
    async with _HUB_LOCK:
        if _HUB is None or (transport and _HUB.transport != transport) or (_HUB and _HUB.down_servers()):
            if _HUB is not None:
                await _HUB.close()
            _HUB = await MCPHub(transport).start()
        return _HUB


async def reset_hub() -> None:
    global _HUB
    if _HUB is not None:
        await _HUB.close()
    _HUB = None
