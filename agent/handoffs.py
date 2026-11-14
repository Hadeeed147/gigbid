"""Structured hand-offs between agents (C3). Anything a later step decides on
is one of these Pydantic objects, never free text."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class JobSpec(BaseModel):
    requirements: list[str] = Field(description="Distinct things the client needs, 2-8 short phrases")
    skills: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    hidden_needs: list[str] = Field(default_factory=list)
    screening_questions: list[str] = Field(default_factory=list)
    budget_note: str | None = None
    timeline: str | None = None
    seniority: Literal["junior", "mid", "senior", "unclear"] = "unclear"


class RiskReport(BaseModel):
    risk_score: float = Field(ge=0, le=1)
    is_scam: bool = False
    flags: list[str] = Field(default_factory=list)
    client_quality: float = Field(default=0.5, ge=0, le=1)
    injection_detected: bool = False
    rationale: str = ""


class RequirementMatch(BaseModel):
    requirement: str
    strength: Literal["strong", "partial", "none"]
    evidence_ids: list[str] = Field(default_factory=list)
    note: str = ""


class FitReport(BaseModel):
    fit_score: float = Field(ge=0, le=1)
    matrix: list[RequirementMatch] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class BidDecision(BaseModel):
    action: Literal["bid", "watch", "skip"]
    reasons: list[str]
    auto: bool = Field(default=False, description="Decided automatically under the user's autonomy setting")


class PriceQuote(BaseModel):
    amount: float
    unit: Literal["hourly", "fixed"]
    band: tuple[float, float]
    connects_cost: int
    connects_worth_it: bool
    rationale: str


class ProposalDraft(BaseModel):
    cover_letter: str
    screening_answers: list[str] = Field(default_factory=list)
    cited_ids: list[str] = Field(default_factory=list)
    revision: int = 0


class CritiqueIssue(BaseModel):
    problem: str
    fix: str


class Critique(BaseModel):
    approved: bool
    score: int = Field(ge=1, le=10)
    issues: list[CritiqueIssue] = Field(default_factory=list)


class Violation(BaseModel):
    rule: str
    quote: str


class ComplianceVerdict(BaseModel):
    verdict: Literal["pass", "rewrite", "block"]
    violations: list[Violation] = Field(default_factory=list)
    cleaned_text: str | None = None


class Intent(BaseModel):
    intent: Literal["question", "negotiation", "interview_request", "scam_signal", "other"]
    confidence: float = Field(ge=0, le=1)
    reason: str = ""


class ReplyDraft(BaseModel):
    text: str
    proposed_slots: list[dict] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    action: Literal["approve", "edit", "reject"]
    text: str | None = None                      # edited cover letter / message
    screening_answers: list[str] | None = None
    bid_amount: float | None = None
    reason: str | None = None                    # required for reject
    slot_start: str | None = None                # conversation: the slot the user picked
