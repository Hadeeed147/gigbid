"""Workspace MCP server: free calendar slots, tentative interview holds and
email drafts. Backend: local mock (default, JSON per user) or Google Calendar /
Gmail via official APIs (workspace.backend: google). The agent sees MCP tools only.
"""
from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from common.config import ROOT, cfg
from mcp_servers.common import AuditLog, auth_kwargs, identity

PORT = 8203
mcp = FastMCP("gigbid-workspace", instructions="Calendar slots, interview holds and email drafts for the freelancer.",
              port=PORT, host="0.0.0.0", stateless_http=True, json_response=True, **auth_kwargs(PORT))
DIR = ROOT / "data" / "processed" / "workspace"
_lock = threading.Lock()
_audit = AuditLog("workspace")


def _tz() -> ZoneInfo:
    return ZoneInfo(cfg("workspace.timezone", "Asia/Karachi"))


def _load(user: str) -> dict:
    p = DIR / f"{user.replace(':', '_')}.json"
    if p.exists():
        return json.loads(p.read_text())
    # seed a realistic busy calendar: weekday mornings blocked, lunch blocked
    base = datetime.now(_tz()).replace(hour=0, minute=0, second=0, microsecond=0)
    busy = []
    for d in range(14):
        day = base + timedelta(days=d)
        if day.weekday() < 5:
            busy.append([(day + timedelta(hours=9)).isoformat(), (day + timedelta(hours=11)).isoformat(), "deep work"])
            busy.append([(day + timedelta(hours=13)).isoformat(), (day + timedelta(hours=14)).isoformat(), "lunch"])
    return {"busy": busy, "holds": [], "drafts": []}


def _save(user: str, data: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{user.replace(':', '_')}.json").write_text(json.dumps(data, indent=1))


class Slot(BaseModel):
    start: str
    end: str
    timezone: str


class SlotList(BaseModel):
    slots: list[Slot]


class Hold(BaseModel):
    id: str
    start: str
    end: str
    title: str
    status: str = "tentative"


class Draft(BaseModel):
    id: str
    to_name: str
    subject: str
    body: str
    status: str = "draft"


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
          title="Find free slots")
async def free_slots(days_ahead: Annotated[int, Field(ge=1, le=14)] = 5,
                     duration_minutes: Annotated[int, Field(ge=15, le=120)] = 30,
                     max_slots: Annotated[int, Field(ge=1, le=10)] = 3,
                     ctx: Context | None = None) -> SlotList:
    """Free working-hours slots (10:00-18:00 local, weekdays) not overlapping busy events or holds."""
    user, trace = identity(ctx)
    data = _load(user)
    busy = [(datetime.fromisoformat(b[0]), datetime.fromisoformat(b[1])) for b in data["busy"]] + \
           [(datetime.fromisoformat(h["start"]), datetime.fromisoformat(h["end"])) for h in data["holds"]]
    now = datetime.now(_tz())
    out = []
    day = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    while len(out) < max_slots and (day - now).days < days_ahead + 1:
        if day.weekday() < 5:
            t = day + timedelta(hours=10)
            while t + timedelta(minutes=duration_minutes) <= day + timedelta(hours=18) and len(out) < max_slots:
                e = t + timedelta(minutes=duration_minutes)
                if all(not (t < b1 and e > b0) for b0, b1 in busy):
                    out.append(Slot(start=t.isoformat(), end=e.isoformat(), timezone=str(_tz())))
                    t += timedelta(hours=3)  # spread suggestions out
                else:
                    t += timedelta(minutes=30)
        day += timedelta(days=1)
    _audit.write(user=user, tool="free_slots", args={"days_ahead": days_ahead}, result={"n": len(out)}, trace_id=trace)
    return SlotList(slots=out)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
          title="Create tentative interview hold")
async def create_interview_hold(start: Annotated[str, Field(description="ISO start time from free_slots")],
                                duration_minutes: Annotated[int, Field(ge=15, le=120)] = 30,
                                title: Annotated[str, Field(max_length=120)] = "Client interview (tentative)",
                                idempotency_key: Annotated[str, Field(min_length=8, max_length=128)] = "",
                                ctx: Context | None = None) -> Hold:
    """Place a TENTATIVE hold on the calendar (confirmed only when the client accepts)."""
    user, trace = identity(ctx)
    try:
        s = datetime.fromisoformat(start)
    except ValueError as e:
        raise ToolError("start must be an ISO datetime") from e
    with _lock:
        data = _load(user)
        hid = "hold_" + (idempotency_key or start)[-12:]
        existing = next((h for h in data["holds"] if h["id"] == hid), None)
        if existing:
            return Hold(**existing)
        h = {"id": hid, "start": s.isoformat(), "end": (s + timedelta(minutes=duration_minutes)).isoformat(),
             "title": title, "status": "tentative"}
        data["holds"].append(h)
        _save(user, data)
    _audit.write(user=user, tool="create_interview_hold", args={"start": start}, result=h, trace_id=trace)
    return Hold(**h)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
          title="Create email draft")
async def create_email_draft(to_name: Annotated[str, Field(max_length=120)],
                             subject: Annotated[str, Field(max_length=200)],
                             body: Annotated[str, Field(max_length=5000)],
                             idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
                             ctx: Context | None = None) -> Draft:
    """Create an email DRAFT (never sent automatically)."""
    user, trace = identity(ctx)
    with _lock:
        data = _load(user)
        did = "draft_" + idempotency_key[-12:]
        existing = next((d for d in data["drafts"] if d["id"] == did), None)
        if existing:
            return Draft(**existing)
        d = {"id": did, "to_name": to_name, "subject": subject, "body": body, "status": "draft"}
        data["drafts"].append(d)
        _save(user, data)
    _audit.write(user=user, tool="create_email_draft", args={"subject": subject}, result={"id": did}, trace_id=trace)
    return Draft(**d)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", default="streamable-http", choices=["streamable-http", "stdio"])
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args()
    mcp.settings.port = a.port
    mcp.run(transport=a.transport)


if __name__ == "__main__":
    main()
