"""Sign-in, onboarding and connected marketplace accounts."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from apps.api import db
from apps.api.auth.security import check_password, create_user, current_user, issue_token
from apps.api.deps import arq
from apps.api.schemas.models import LoginIn, OnboardingIn, RegisterIn, SessionOut, UserOut
from common import token_store
from common.config import env

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(u: dict) -> UserOut:
    return UserOut(id=u["id"], email=u["email"], name=u["name"], tenant=u["tenant"], onboarded=u["onboarded"],
                   settings=u.get("settings") or {})


@router.post("/register", response_model=SessionOut)
def register(body: RegisterIn) -> SessionOut:
    if db.one("SELECT 1 FROM users WHERE email=%s", (body.email.lower(),)):
        raise HTTPException(409, "email already registered")
    u = create_user(body.email, body.password, body.name)
    return SessionOut(token=issue_token(u["id"]), user=_user_out(u))


@router.post("/login", response_model=SessionOut)
def login(body: LoginIn) -> SessionOut:
    u = db.one("SELECT * FROM users WHERE email=%s", (body.email.lower(),))
    if not u or not check_password(body.password, u["password_hash"]):
        raise HTTPException(401, "wrong email or password")
    return SessionOut(token=issue_token(u["id"]), user=_user_out(u))


@router.get("/me", response_model=UserOut)
def me(user: dict = Depends(current_user)) -> UserOut:
    return _user_out(user)


@router.post("/onboarding", response_model=UserOut)
async def onboarding(body: OnboardingIn, user: dict = Depends(current_user), pool=Depends(arq)) -> UserOut:
    tenant = user["id"] if body.profile == "own" else body.profile
    settings = {**(user.get("settings") or {}), "rate_floor": body.rate_floor, "hourly_rate": body.hourly_rate,
                "weekly_connects_budget": body.weekly_connects_budget, "marketplace": body.marketplace,
                "autonomy": (user.get("settings") or {}).get("autonomy", "suggest_only")}
    db.q("UPDATE users SET tenant=%s, settings=%s, onboarded=true WHERE id=%s", (tenant, db.jb(settings), user["id"]))
    if body.gigsim_token:
        token_store.put(user["id"], "gigsim", {"token": body.gigsim_token})
    db.q("DELETE FROM saved_searches WHERE user_id=%s", (user["id"],))
    for s in body.searches or [{"query": "", "category": "", "interval_minutes": 10}]:
        s = s if isinstance(s, dict) else s.model_dump()
        db.q("INSERT INTO saved_searches (id, user_id, query, category, interval_minutes) VALUES (%s,%s,%s,%s,%s)",
             ("s_" + uuid.uuid4().hex[:8], user["id"], s["query"], s["category"], s["interval_minutes"]))
    await pool.enqueue_job("scout_user", user["id"], True, _job_id=f"scout-now:{user['id']}:{uuid.uuid4().hex[:6]}")
    return _user_out(db.one("SELECT * FROM users WHERE id=%s", (user["id"],)))


# --------------------------------------------------------------- live Upwork OAuth 2.1
@router.get("/upwork/start")
async def upwork_start(user: dict = Depends(current_user)) -> dict:
    """Begins the official Upwork MCP OAuth flow; returns the authorisation URL to open."""
    from mcp_servers.marketplace.adapters import upwork_live as up
    if not env("UPWORK_OAUTH_REDIRECT_URI"):
        raise HTTPException(400, "live mode not configured on this deployment")
    up.PENDING[user["id"]] = {}

    async def connect():
        from langchain_mcp_adapters.client import MultiServerMCPClient
        client = MultiServerMCPClient({"upwork": {"transport": "streamable_http", "url": env("UPWORK_MCP_URL"),
                                                  "auth": up.oauth_provider(user["id"], interactive=True)}})
        await client.get_tools()
    task = asyncio.create_task(connect())
    for _ in range(50):
        await asyncio.sleep(0.1)
        if up.PENDING[user["id"]].get("url"):
            up.PENDING[user["id"]]["task"] = task
            return {"authorize_url": up.PENDING[user["id"]]["url"]}
    raise HTTPException(502, "Upwork MCP did not return an authorisation URL")


@router.get("/upwork/callback")
async def upwork_callback(code: str, state: str | None = None):
    from mcp_servers.marketplace.adapters import upwork_live as up
    for _uid, p in up.PENDING.items():
        fut = p.get("code_future")
        if fut and not fut.done():
            fut.set_result((code, state))
            break
    return RedirectResponse(env("WEB_PUBLIC_URL", "/") + "/settings?connected=upwork")


@router.get("/accounts")
def accounts(user: dict = Depends(current_user)) -> dict:
    s = user.get("settings") or {}
    return {"marketplace": s.get("marketplace", "gigsim"),
            "gigsim": "own account" if token_store.get(user["id"], "gigsim") else f"persona account ({user['tenant']})",
            "upwork": bool(token_store.get(user["id"], "upwork_oauth"))}


@router.delete("/accounts/{provider}")
def disconnect(provider: str, user: dict = Depends(current_user)) -> dict:
    for p in ({"upwork": ["upwork_oauth", "upwork_client"], "gigsim": ["gigsim"]}.get(provider) or []):
        token_store.delete(user["id"], p)
    return {"ok": True}
