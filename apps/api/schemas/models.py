"""Request and response models. These drive the OpenAPI schema from which the
web app's TypeScript client is generated (apps/web/src/lib/api, do not hand-edit)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    tenant: str
    onboarded: bool
    settings: dict[str, Any] = {}


class SessionOut(BaseModel):
    token: str
    user: UserOut


class SavedSearchIn(BaseModel):
    query: str = Field(default="", max_length=200)
    category: str = Field(default="", max_length=80)
    interval_minutes: int = Field(default=10, ge=5, le=1440)


class SavedSearchOut(SavedSearchIn):
    id: str
    last_run: str | None = None


class OnboardingIn(BaseModel):
    profile: Literal["ai_ml", "fullstack", "data_analyst", "own"]
    marketplace: Literal["gigsim", "upwork_live"] = "gigsim"
    gigsim_token: str | None = Field(default=None, description="Own GigSim account token (optional)")
    rate_floor: float = Field(gt=0, le=1000)
    hourly_rate: float = Field(gt=0, le=1000)
    weekly_connects_budget: int = Field(ge=0, le=1000)
    searches: list[SavedSearchIn] = []


class SettingsIn(BaseModel):
    display_name: str | None = None
    rate_floor: float | None = Field(default=None, gt=0, le=1000)
    hourly_rate: float | None = Field(default=None, gt=0, le=1000)
    weekly_connects_budget: int | None = Field(default=None, ge=0, le=1000)
    autonomy: Literal["suggest_only", "auto_skip_low_fit"] | None = None


class InboxItem(BaseModel):
    job_id: str
    thread_id: str
    title: str
    category: str | None = None
    status: str
    action: str | None = None
    fit: float | None = None
    risk: float | None = None
    is_scam: bool = False
    flags: list[str] = []
    price: dict | None = None
    connects_cost: int | None = None
    budget: dict | None = None
    reasons: list[str] = []
    attention_reason: str | None = None
    trace_url: str | None = None
    updated_at: str | None = None


class InboxOut(BaseModel):
    items: list[InboxItem]
    total: int


class JobDetail(BaseModel):
    item: InboxItem
    job: dict[str, Any]
    job_spec: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None
    fit: dict[str, Any] | None = None
    evidence: dict[str, list[dict]] = {}
    decision: dict[str, Any] | None = None
    price: dict[str, Any] | None = None
    usage: dict[str, Any] = {}
    status: str | None = None


class StudioOut(BaseModel):
    job_id: str
    thread_id: str
    status: str | None
    pending: bool
    payload: dict[str, Any] | None = None
    submission: dict[str, Any] | None = None
    approvals: list[dict] = []
    attention_reason: str | None = None


class ApprovalIn(BaseModel):
    action: Literal["approve", "edit", "reject"]
    text: str | None = Field(default=None, max_length=6000)
    screening_answers: list[str] | None = None
    bid_amount: float | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=500)
    slot_start: str | None = None


class QueuedOut(BaseModel):
    queued: bool
    job: str
    trace_id: str


class ParagraphIn(BaseModel):
    paragraph: str = Field(min_length=1, max_length=3000)
    instruction: str = Field(default="Make it more specific", max_length=300)


class ParagraphOut(BaseModel):
    paragraph: str


class PipelineCard(BaseModel):
    proposal_id: str
    job_id: str
    title: str | None = None
    category: str | None = None
    stage: str
    connects_spent: int = 0
    thread_id: str | None = None
    updated_at: str | None = None


class ConversationOut(BaseModel):
    thread_id: str
    job_id: str | None = None
    title: str | None = None
    status: str
    intent: str | None = None
    last_message: str | None = None
    updated_at: str | None = None


class ThreadOut(BaseModel):
    conversation: ConversationOut
    messages: list[dict]
    pending: dict[str, Any] | None = None


class RunOut(BaseModel):
    id: str
    thread_id: str
    kind: str
    status: str
    trace_id: str | None = None
    trace_url: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


class RunDetail(BaseModel):
    run: RunOut | None
    events: list[dict]


class AnalyticsOut(BaseModel):
    by_category: list[dict]
    connects: dict[str, Any]
    cost_latency: dict[str, Any]
    rejection_reasons: list[dict]
    funnel: dict[str, int]


class MemoryOut(BaseModel):
    style: list[dict]
    outcome: list[dict]


class PortfolioItemIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    text: str = Field(min_length=40, max_length=20000)
    type: Literal["case_study", "review", "readme"] = "case_study"


class PortfolioItemOut(BaseModel):
    item_id: str
    title: str
    type: str
    source: str
    chunks_indexed: int | None = None


class HealthOut(BaseModel):
    api: bool
    marketplace: dict[str, Any]
    mode: str
    profile: str
