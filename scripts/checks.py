"""Repository rules enforced in CI:

  1. no secrets in the repo (key-shaped strings, private keys, a committed .env)
  2. nothing under gigsim/ changed (hash of the frozen simulator vs gigsim/CHECKSUM)
  3. every prompt lives in agent/prompts/ (no long system prompts inline in Python)
  4. every number in README.md and docs/REPORT.md traces to a file in evals/results/
     (numbers inside results tables must appear in some results JSON)

Run:  uv run python -m scripts.checks [--write-gigsim-checksum]
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIGSIM_FILES = ["gigsim/server.py", "gigsim/client_model.py", "gigsim/policies.py"]
SECRET_PATTERNS = [
    r"gsk_[A-Za-z0-9]{20,}",               # Groq
    r"sk-[A-Za-z0-9_-]{20,}",              # OpenAI-style
    r"lsv2_[A-Za-z0-9_]{20,}",             # LangSmith
    r"ghp_[A-Za-z0-9]{30,}",               # GitHub PAT
    r"-----BEGIN (RSA |EC )?PRIVATE KEY-----",
    r"AKIA[0-9A-Z]{16}",                   # AWS
]


def tracked() -> list[str]:
    return subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()


def check_secrets(files: list[str]) -> list[str]:
    errs = []
    if ".env" in files:
        errs.append(".env is committed")
    for f in files:
        p = ROOT / f
        if p.suffix in {".png", ".jpg", ".pdf", ".sqlite", ".onnx", ".gif", ".ico"} or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pat in SECRET_PATTERNS:
            if re.search(pat, text):
                errs.append(f"possible secret in {f} ({pat[:12]}...)")
    return errs


def gigsim_hash() -> str:
    h = hashlib.sha256()
    for f in GIGSIM_FILES:
        h.update((ROOT / f).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def check_gigsim() -> list[str]:
    ck = ROOT / "gigsim" / "CHECKSUM"
    if not ck.exists():
        return ["gigsim/CHECKSUM missing (run make gigsim-checksum once)"]
    return [] if ck.read_text().strip() == gigsim_hash() else ["gigsim/ was modified (frozen simulator)"]


def check_prompts(files: list[str]) -> list[str]:
    errs = []
    for f in files:
        if not f.endswith(".py") or f.startswith(("evals/", "tests/", "data/generators/", "scripts/")) or "/tests/" in f:
            continue
        text = (ROOT / f).read_text(encoding="utf-8")
        for m in re.finditer(r'"role":\s*"system",\s*"content":\s*"([^"]{120,})"', text):
            errs.append(f"inline system prompt in {f}: {m.group(1)[:40]}...")
    return errs


def numbers_in_results() -> set[str]:
    nums: set[str] = set()
    for p in (ROOT / "evals" / "results").glob("*.json"):
        for m in re.finditer(r"-?\d+\.\d+|\d+", p.read_text(encoding="utf-8")):
            v = m.group(0)
            nums.add(v)
            try:
                x = float(v)
                for nd in (0, 1, 2, 3):
                    nums.add(f"{round(x, nd):.{nd}f}")
                    nums.add(f"{round(x * 100, nd):.{nd}f}")      # rates shown as percentages
            except ValueError:
                pass
    return nums


def check_numbers() -> list[str]:
    """Numbers inside tables marked <!-- results --> ... <!-- /results --> must exist in evals/results."""
    known = numbers_in_results()
    errs = []
    for doc in ("README.md", "docs/REPORT.md"):
        p = ROOT / doc
        if not p.exists():
            continue
        for block in re.findall(r"<!-- results -->(.*?)<!-- /results -->", p.read_text(encoding="utf-8"), re.S):
            for v in re.findall(r"(?<![\w.])\d+\.\d+(?![\w.])", block):
                if v not in known:
                    errs.append(f"{doc}: {v} does not appear in evals/results/")
    return errs


def main() -> None:
    if "--write-gigsim-checksum" in sys.argv:
        (ROOT / "gigsim" / "CHECKSUM").write_text(gigsim_hash() + "\n")
        print("gigsim/CHECKSUM written")
        return
    files = tracked()
    errs = check_secrets(files) + check_gigsim() + check_prompts(files) + check_numbers()
    for e in errs:
        print("FAIL:", e)
    print(json.dumps({"checks": 4, "failures": len(errs)}))
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
