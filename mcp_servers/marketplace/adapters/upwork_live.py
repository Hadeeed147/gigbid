"""Live Upwork adapter: the official Upwork MCP server over Streamable HTTP with OAuth 2.1.

- Auth: the MCP SDK's OAuthClientProvider (discovery, dynamic client registration,
  PKCE). Tokens are persisted per user, encrypted, via common.token_store; never logged.
- Tool names are mapped in agent/config.yaml (marketplace.upwork_tool_map) so the
  port stays stable if Upwork renames tools. Run
      uv run python -m mcp_servers.marketplace.adapters.upwork_live --discover <user_id>
  after connecting to print the live tool list and fix the map.
- Writes only ever create DRAFTS; the user confirms them on Upwork (platform rule).
- No scraping, no browser automation, no session cookies.
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
from typing import Any

from agent.marketplace_port import ClientHistory, Job, MarketplaceRejected, MarketplaceUnavailable
from common import token_store
from common.config import cfg, env

DEFAULT_MAP = {
    "search_jobs": "search_jobs", "get_job": "get_job_details", "get_client_history": "get_client_details",
    "get_connects_balance": "get_connects_balance", "list_threads": "list_rooms", "list_messages": "get_room_messages",
    "create_proposal_draft": "create_proposal_draft", "send_message": "create_message_draft",
}


class EncryptedTokenStorage:
    """mcp.client.auth.TokenStorage backed by the encrypted per-user store."""

    def __init__(self, user: str):
        self.user = user

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken
        raw = token_store.get(self.user, "upwork_oauth")
        return OAuthToken(**raw) if raw else None

    async def set_tokens(self, tokens) -> None:
        token_store.put(self.user, "upwork_oauth", tokens.model_dump(mode="json"))

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull
        raw = token_store.get(self.user, "upwork_client")
        return OAuthClientInformationFull(**raw) if raw else None

    async def set_client_info(self, client_info) -> None:
        token_store.put(self.user, "upwork_client", client_info.model_dump(mode="json"))


# Pending authorisations: user -> {"url": str | None, "code_future": Future}
PENDING: dict[str, dict] = {}


def oauth_provider(user: str, interactive: bool = False):
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata

    async def redirect_handler(url: str) -> None:
        if not interactive:
            raise MarketplaceRejected(401, "Upwork not connected: start OAuth from Settings > Connected accounts")
        PENDING.setdefault(user, {})["url"] = url

    async def callback_handler() -> tuple[str, str | None]:
        fut = PENDING.setdefault(user, {}).setdefault("code_future", asyncio.get_running_loop().create_future())
        return await fut

    meta = OAuthClientMetadata(client_name="GigBid", redirect_uris=[env("UPWORK_OAUTH_REDIRECT_URI")],
                               grant_types=["authorization_code", "refresh_token"], response_types=["code"])
    return OAuthClientProvider(server_url=env("UPWORK_MCP_URL", "https://mcp.upwork.com/mcp"), client_metadata=meta,
                               storage=EncryptedTokenStorage(user), redirect_handler=redirect_handler,
                               callback_handler=callback_handler)


class UpworkLiveAdapter:
    name = "upwork_live"

    def __init__(self):
        self.map = {**DEFAULT_MAP, **(cfg("marketplace.upwork_tool_map") or {})}

    def _run(self, coro):
        out: dict = {}

        def target():
            try:
                out["v"] = asyncio.run(coro)
            except Exception as e:  # surface in the caller's thread
                out["e"] = e
        t = threading.Thread(target=target)
        t.start()
        t.join(cfg("node_runtime.timeout_s", 60))
        if "e" in out:
            e = out["e"]
            if isinstance(e, (MarketplaceRejected, MarketplaceUnavailable)):
                raise e
            raise MarketplaceUnavailable(f"Upwork MCP error: {e}")
        if "v" not in out:
            raise MarketplaceUnavailable("Upwork MCP timed out")
        return out["v"]

    async def _call(self, user: str, port_method: str, args: dict) -> Any:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        client = MultiServerMCPClient({"upwork": {"transport": "streamable_http",
                                                  "url": env("UPWORK_MCP_URL", "https://mcp.upwork.com/mcp"),
                                                  "auth": oauth_provider(user)}})
        tools = {t.name: t for t in await client.get_tools(server_name="upwork")}
        name = self.map.get(port_method)
        if name not in tools:
            raise MarketplaceRejected(501, f"Upwork MCP has no tool '{name}' for {port_method}; "
                                           f"available: {sorted(tools)[:20]}")
        res = await tools[name].ainvoke(args)
        if isinstance(res, str):
            try:
                return json.loads(res)
            except json.JSONDecodeError:
                return {"text": res}
        return res

    def call(self, user, method, args):
        return self._run(self._call(user, method, args))

    # -- read
    def search_jobs(self, user, query="", category="", posted_after="", limit=20):
        data = self.call(user, "search_jobs", {"query": query, "limit": limit})
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        return [Job(id=str(j.get("id")), title=j.get("title", ""), description=j.get("description", ""),
                    category=j.get("category"), source="upwork") for j in (jobs or [])]

    def get_job(self, user, job_id):
        j = self.call(user, "get_job", {"job_id": job_id})
        return Job(id=str(j.get("id", job_id)), title=j.get("title", ""), description=j.get("description", ""),
                   source="upwork")

    def get_client_history(self, user, client_id):
        c = self.call(user, "get_client_history", {"client_id": client_id})
        return ClientHistory(id=client_id, **{k: v for k, v in c.items() if k in ClientHistory.model_fields})

    def get_connects_balance(self, user):
        return int(self.call(user, "get_connects_balance", {}).get("balance", 0))

    def get_policy(self, user):
        return {"version": "upwork", "summary": "Upwork Terms of Service apply; drafts only."}

    def list_threads(self, user):
        return self.call(user, "list_threads", {}).get("rooms", [])

    def list_messages(self, user, thread_id):
        return self.call(user, "list_messages", {"room_id": thread_id}).get("messages", [])

    def list_events(self, user, after_seq=0):
        return []  # Upwork has no event feed via MCP; pipeline refreshes from proposal/room state

    # -- write: drafts only, user confirms on Upwork
    def create_proposal_draft(self, user, job_id, cover_letter, bid_amount, screening_answers, idempotency_key,
                              dry_run, extra=None):
        preview = {"job_id": job_id, "cover_letter": cover_letter, "bid_amount": bid_amount,
                   "screening_answers": screening_answers, "note": "Created as an Upwork DRAFT; confirm on Upwork."}
        if dry_run:
            return {"dry_run": True, "would_create": preview}
        res = self.call(user, "create_proposal_draft", {"job_id": job_id, "cover_letter": cover_letter,
                                                        "bid_amount": bid_amount, "answers": screening_answers})
        return {"id": str(res.get("id", idempotency_key)), "status": "draft_on_upwork", **preview}

    def submit_proposal(self, user, proposal_id, idempotency_key, dry_run, extra=None):
        # The platform requires the user to confirm the draft on Upwork itself.
        return {"id": proposal_id, "status": "awaiting_confirmation_on_upwork", "dry_run": dry_run}

    def send_message(self, user, thread_id, text, idempotency_key, dry_run):
        if dry_run:
            return {"dry_run": True, "would_send": {"thread_id": thread_id, "text": text}}
        res = self.call(user, "send_message", {"room_id": thread_id, "text": text})
        return {"id": str(res.get("id", idempotency_key)), "status": "draft_on_upwork"}


if __name__ == "__main__" and "--discover" in sys.argv:
    user = sys.argv[-1]

    async def discover():
        from langchain_mcp_adapters.client import MultiServerMCPClient
        client = MultiServerMCPClient({"upwork": {"transport": "streamable_http",
                                                  "url": env("UPWORK_MCP_URL", "https://mcp.upwork.com/mcp"),
                                                  "auth": oauth_provider(user)}})
        for t in await client.get_tools():
            print(t.name, "-", (t.description or "")[:90])
    asyncio.run(discover())
