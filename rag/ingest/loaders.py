"""Loaders for every evidence type: PDF CV, Markdown case studies, repo READMEs
and code, client reviews and past proposals. Each returns raw items that the
chunkers turn into Chunks with full metadata.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from data.generators.skills import SKILLS

CODE_EXT = {".py", ".ts", ".tsx", ".js", ".sql", ".ipynb"}


@dataclass
class RawItem:
    item_id: str
    type: str
    tenant: str
    text: str
    title: str = ""
    project_id: str | None = None
    date: str = ""
    client_industry: str = ""
    outcome: str | None = None
    source: str = "synthetic"
    extra: dict = field(default_factory=dict)


_SKILL_PATTERNS = {
    sid: re.compile(r"(?i)(?<![\w])(" + "|".join(re.escape(n) for n in v["names"]) + r")(?![\w])")
    for sid, v in SKILLS.items()
}
# code imports reveal skills that READMEs hide (V5 motivation)
_IMPORT_HINTS = {"celery": "celery", "fastapi": "fastapi", "torch": "pytorch", "transformers": "transformers",
                 "langchain": "langchain", "langgraph": "langgraph", "qdrant_client": "vector_db",
                 "cv2": "computer_vision", "ultralytics": "computer_vision", "mlflow": "mlops", "sklearn": "sklearn",
                 "prophet": "forecasting", "airflow": "airflow", "pandas": "pandas", "redis": "redis",
                 "django": "django", "express": "nodejs", "stripe": "stripe", "react": "react", "scipy": "statistics",
                 "statsmodels": "ab_testing"}


def tag_skills(text: str) -> list[str]:
    found = [sid for sid, pat in _SKILL_PATTERNS.items() if pat.search(text)]
    for mod, sid in _IMPORT_HINTS.items():
        if re.search(rf"(?m)^\s*(from|import)\s+{mod}\b|require\('{mod}'\)|from '{mod}'", text) and sid not in found:
            found.append(sid)
    return found


def _frontmatter(md: str) -> tuple[dict, str]:
    if md.startswith("---\n"):
        _, fm, body = md.split("---\n", 2)
        try:
            return json.loads(fm), body
        except json.JSONDecodeError:
            import yaml
            return yaml.safe_load(fm) or {}, body
    return {}, md


def load_pdf(path: Path) -> str:
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def load_persona_dir(pdir: Path, tenant: str) -> list[RawItem]:
    items: list[RawItem] = []
    # CV: prefer the PDF (exercises the PDF loader); fall back to markdown
    if (pdir / "cv.pdf").exists():
        items.append(RawItem(f"{tenant}:cv", "cv", tenant, load_pdf(pdir / "cv.pdf"), title="CV"))
    elif (pdir / "cv.md").exists():
        items.append(RawItem(f"{tenant}:cv", "cv", tenant, (pdir / "cv.md").read_text(encoding="utf-8"), title="CV"))

    for f in sorted((pdir / "case_studies").glob("*.md")) if (pdir / "case_studies").exists() else []:
        meta, body = _frontmatter(f.read_text(encoding="utf-8"))
        title = next((ln.lstrip("# ").strip() for ln in body.splitlines() if ln.startswith("# ")), f.stem)
        items.append(RawItem(meta.get("id", f"{tenant}:cs:{f.stem}"), "case_study", tenant, body, title=title,
                             project_id=meta.get("project_id"), date=meta.get("date", ""),
                             client_industry=meta.get("client_industry", ""), source=meta.get("source", "user")))

    for rdir in sorted((pdir / "repos").iterdir()) if (pdir / "repos").exists() else []:
        if not rdir.is_dir():
            continue
        meta = json.loads((rdir / ".gigbid.json").read_text()) if (rdir / ".gigbid.json").exists() else {}
        pid = meta.get("project_id")
        if (rdir / "README.md").exists():
            items.append(RawItem(f"{tenant}:readme:{rdir.name}", "readme", tenant,
                                 (rdir / "README.md").read_text(encoding="utf-8"), title=f"{rdir.name} README",
                                 project_id=pid, date=str(meta.get("year", "")), source=meta.get("source", "user")))
        for cf in sorted(rdir.iterdir()):
            if cf.suffix in CODE_EXT:
                items.append(RawItem(f"{tenant}:code:{rdir.name}:{cf.name}", "code", tenant,
                                     cf.read_text(encoding="utf-8"), title=f"{rdir.name}/{cf.name}", project_id=pid,
                                     date=str(meta.get("year", "")), source=meta.get("source", "user")))

    if (pdir / "reviews.json").exists():
        for r in json.loads((pdir / "reviews.json").read_text(encoding="utf-8")):
            items.append(RawItem(r["id"], "review", tenant, r["text"], title=f"Client review ({r.get('rating')}★)",
                                 project_id=r.get("project_id"), date=r.get("date", ""),
                                 client_industry=r.get("client_industry", ""), source=r.get("source", "user")))

    if (pdir / "proposals.json").exists():
        for p in json.loads((pdir / "proposals.json").read_text(encoding="utf-8")):
            items.append(RawItem(p["id"], "proposal", tenant, p["text"], title=p.get("job_title", ""),
                                 date=p.get("date", ""), outcome=p.get("outcome"), source=p.get("source", "user"),
                                 extra={"cited_projects": p.get("cited_projects", []),
                                        "job_category": p.get("job_category"), "job_skills": p.get("job_skills", [])}))
    return items
