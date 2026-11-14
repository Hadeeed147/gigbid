"""Chunkers: structure-aware (headings, bullets, code blocks) and fixed-size (V0)."""
from __future__ import annotations

import re

from rag.ingest.loaders import RawItem, tag_skills
from rag.types import Chunk


def _mk(item: RawItem, idx: int, text: str, item_skills: list[str]) -> Chunk:
    skills = sorted(set(tag_skills(text)) | set(item_skills))
    return Chunk(chunk_id=f"{item.item_id}#{idx}", item_id=item.item_id, text=text.strip(), type=item.type,
                 tenant=item.tenant, project_id=item.project_id, title=item.title, skills=skills, date=item.date,
                 client_industry=item.client_industry, outcome=item.outcome, source=item.source)


def structured_chunks(item: RawItem, size: int = 700) -> list[Chunk]:
    """Split on markdown sections; keep each section's heading as a prefix.

    Small items (reviews, proposals, code files) stay whole: splitting them
    loses the meaning (code imports + body belong together).
    """
    item_skills = tag_skills(item.text)
    if item.type in ("review", "proposal", "code") or len(item.text) <= size:
        return [_mk(item, 0, f"{item.title}\n{item.text}", item_skills)]
    sections = re.split(r"(?m)^(?=#{1,3} )", item.text)
    chunks, buf = [], ""
    for sec in sections:
        if not sec.strip():
            continue
        if len(buf) + len(sec) > size and buf:
            chunks.append(buf)
            buf = ""
        buf += sec
    if buf:
        chunks.append(buf)
    return [_mk(item, i, f"{item.title}\n{c}" if not c.startswith("# ") else c, item_skills)
            for i, c in enumerate(chunks)]


def fixed_chunks(item: RawItem, size: int = 500, overlap: int = 50) -> list[Chunk]:
    """Naive fixed windows with no structure and no title prefix (V0 baseline)."""
    text = item.text
    out, i, n = [], 0, 0
    while i < len(text):
        out.append(_mk(item, n, text[i:i + size], []))
        i += size - overlap
        n += 1
    return out
