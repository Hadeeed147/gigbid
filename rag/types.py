"""Core RAG data types."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Chunk:
    chunk_id: str
    item_id: str              # evidence item (case study, readme, code file, review, cv, proposal)
    text: str
    type: str                 # case_study | readme | code | review | cv | proposal
    tenant: str               # persona id or user id: every query is scoped by tenant
    project_id: str | None = None
    title: str = ""
    skills: list[str] = field(default_factory=list)
    date: str = ""
    client_industry: str = ""
    outcome: str | None = None          # proposals only: won | replied | ignored
    source: str = "synthetic"
    context: str = ""                   # optional contextual line (V6)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Hit:
    chunk: Chunk
    score: float
    requirement: str | None = None
    retriever: str = ""

    @property
    def item_id(self) -> str:
        return self.chunk.item_id

    def to_evidence(self) -> dict:
        c = self.chunk
        return {"item_id": c.item_id, "chunk_id": c.chunk_id, "type": c.type, "project_id": c.project_id,
                "title": c.title, "source": c.source, "date": c.date, "outcome": c.outcome,
                "client_industry": c.client_industry, "text": c.text, "score": round(float(self.score), 4),
                "requirement": self.requirement}
