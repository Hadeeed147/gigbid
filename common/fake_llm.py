"""Deterministic TEST DOUBLE for the LLM (GIGBID_FAKE_LLM=1).

Used only by CI, unit/integration tests and Playwright so the whole graph can run
without an API key. Never used for any reported number: every result in
evals/results/ records the real model ids it was produced with.
"""
from __future__ import annotations

import os
import re
from typing import Any

from pydantic import BaseModel

CITE = re.compile(r"\[([a-z_]+:[a-z_]+:[^\]\s]+)\]")


def enabled() -> bool:
    return os.environ.get("GIGBID_FAKE_LLM") == "1"


def _content(messages: list[dict]) -> str:
    return "\n".join(m["content"] for m in messages)


def respond(node: str, messages: list[dict], schema: type[BaseModel] | None) -> Any:
    text = _content(messages)
    name = schema.__name__ if schema else ""
    if name == "JobSpec":
        from rag.variants.base import rule_requirements
        body = text.split("<untrusted_job_post>")[-1].split("</untrusted_job_post>")[0]
        qs = re.findall(r"Q\d+: (.+)", body)
        return schema(requirements=rule_requirements(body)[:6] or ["general help"], screening_questions=qs)
    if name == "RiskReport":
        return schema(risk_score=0.1, rationale="fake: no LLM risk signal", client_quality=0.7)
    if name == "FitReport":
        reqs = re.findall(r"REQUIREMENT: (.+)", text)
        matrix = []
        for block, req in zip(text.split("REQUIREMENT: ")[1:], reqs, strict=False):
            ids = re.findall(r"\[([^\]]+)\] \((?:case_study|readme|code|review|cv)", block)
            scores = [float(x) for x in re.findall(r"score ([\d.]+)\)", block)]
            strength = "strong" if scores and scores[0] >= 0.5 else ("partial" if ids else "none")
            matrix.append({"requirement": req, "strength": strength, "evidence_ids": ids[:2]})
        return schema(fit_score=0.0, matrix=matrix, reasons=["fake matcher"])
    if name == "ProposalDraft":
        ids = re.findall(r"^\[([a-z_]+:[a-z_]+:[^\]\s]+)\]", text, flags=re.M)[:3]
        title = re.search(r"Title: (.+)", text)
        t = title.group(1) if title else "your project"
        sents = [f"For {t.lower()}, the closest match in my work is the project in {ids[0]} [{ids[0]}]." if ids else
                 f"For {t.lower()}, here is how I would approach it."]
        for i in ids[1:]:
            sents.append(f"I also built the related system described in {i} [{i}].")
        sents.append("I would start with a short discovery call, then ship a first working slice in week one and "
                     "review it with you before building the rest. The plan keeps scope small, tested and documented "
                     "so your team can maintain it after handover, with clear weekly updates on progress and risks.")
        sents.append("Which part of the current setup causes the most trouble today?")
        qs = re.findall(r"Screening questions to answer, in order: \[(.*)\]", text)
        n_q = len(re.findall(r"'[^']+'", qs[0])) if qs else 0
        return schema(cover_letter="\n\n".join(sents), screening_answers=[
            f"Based on my portfolio work [{ids[0]}], I would handle this with a tested, incremental plan." if ids
            else "I would handle this with a tested, incremental plan and weekly check-ins." for _ in range(n_q)])
    if name == "Critique":
        loop = os.environ.get("GIGBID_FAKE_CRITIC_LOOP") == "1" and "REVISION REQUEST" not in text
        return schema(approved=not loop, score=6 if loop else 8,
                      issues=[{"problem": "opening could be more specific", "fix": "name the client's problem"}] if loop else [])
    if name == "ComplianceVerdict":
        return schema(verdict="pass", violations=[], cleaned_text=None)
    if name == "ClaimVerdict":
        claim = re.search(r"<claim>(.*?)</claim>", text, re.S)
        ids = CITE.findall(claim.group(1) if claim else "")
        return schema(status="supported" if ids else "unsupported", evidence_ids=ids)
    if name == "Intent":
        low = text.lower()
        intent = ("scam_signal" if re.search(r"whatsapp|telegram|outside", low) else
                  "interview_request" if re.search(r"call|interview", low) else
                  "negotiation" if re.search(r"budget|less|discount", low) else "question")
        return schema(intent=intent, confidence=0.9, reason="fake keyword intent")
    if name == "ReplyDraft":
        if "scam_signal" in text:
            return schema(text="Thanks for the message. I keep all communication and payments on the platform, "
                               "so let's continue here. Happy to answer any questions about the project.")
        return schema(text="Thanks for getting back to me. Happy to walk you through the approach and the first "
                           "milestone. Would one of the proposed times work for a short call?")
    if name == "JudgeScore":
        return schema(score=6, reason="fake judge")
    if schema is not None:
        return schema.model_validate({})
    return "fake response"
