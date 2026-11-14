"""Prompts live in agent/prompts/<node>.md (one versioned file per node, no inline prompts).

Each file starts with a front-matter line `version: N`; the version is attached
to traces so a regression can be tied to a prompt change.
"""
from __future__ import annotations

from functools import lru_cache

from common.config import ROOT

PROMPTS = ROOT / "agent" / "prompts"


@lru_cache(maxsize=64)
def _read(node: str) -> tuple[str, str]:
    raw = (PROMPTS / f"{node}.md").read_text(encoding="utf-8")
    version = "0"
    if raw.startswith("---"):
        _, fm, raw = raw.split("---", 2)
        for line in fm.splitlines():
            if line.startswith("version:"):
                version = line.split(":", 1)[1].strip()
    return raw.strip(), version


def load_prompt(node: str, **vars: str) -> str:
    text, _ = _read(node)
    for k, v in vars.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def prompt_version(node: str) -> str:
    return _read(node)[1]
