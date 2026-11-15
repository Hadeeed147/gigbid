"""Deploy the last commit to a Hugging Face Docker Space (the public demo URL).

What it does:
  1. creates the Space <user>/gigbid (Docker SDK) if it does not exist;
  2. copies the needed values from .env into the Space as *secrets* (never into files);
  3. uploads `git archive HEAD` (so the deployment is exactly the last commit) plus
     infra/deploy/Dockerfile at the root and a Space README with the Docker front matter.

Needs HF_TOKEN (write) in .env.   Run:  uv run python -m scripts.deploy_hf [--secrets-only|--code-only]
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

from dotenv import dotenv_values
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
SPACE_NAME = "gigbid"
SECRETS = ["GROQ_API_KEY", "OPENROUTER_API_KEY", "LANGSMITH_API_KEY", "NEON_DATABASE_URL", "JWT_SECRET",
           "TOKEN_ENCRYPTION_KEY", "REVIEWER_EMAIL", "REVIEWER_PASSWORD", "MCP_BEARER_TOKEN", "GIGSIM_ADMIN_KEY",
           "GITHUB_PERSONAL_ACCESS_TOKEN", "UPWORK_OAUTH_CLIENT_ID", "UPWORK_OAUTH_CLIENT_SECRET"]
VARIABLES = ["GIGBID_RAG_VARIANT", "LANGSMITH_TRACING", "LANGSMITH_PROJECT"]

SPACE_README = """---
title: GigBid
emoji: 🧭
colorFrom: indigo
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: Multi-agent freelancer copilot; a human approves every send
---

GigBid: LangGraph agents find freelance jobs on a marketplace simulator (GigSim), decide whether to
bid, write proposals grounded in portfolio evidence and wait for human approval before anything is sent.

Code, results and report: https://github.com/Hadeeed147/gigbid
"""


def clean(v: str | None) -> str:
    return (v or "").split(" #")[0].strip()


def main() -> None:
    env = {k: clean(v) for k, v in dotenv_values(ROOT / ".env").items()}
    api = HfApi(token=env.get("HF_TOKEN") or None)
    user = api.whoami()["name"]
    repo_id = f"{user}/{SPACE_NAME}"
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True, private=False)
    print(f"space: https://huggingface.co/spaces/{repo_id}  ->  https://{user}-{SPACE_NAME}.hf.space")

    if "--code-only" not in sys.argv:
        for k in SECRETS:
            if env.get(k):
                api.add_space_secret(repo_id, k, env[k])
        for k in VARIABLES:
            if env.get(k):
                api.add_space_variable(repo_id, k, env[k])
        print("secrets set:", [k for k in SECRETS if env.get(k)])

    if "--secrets-only" in sys.argv:
        return
    sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True)
    if dirty.strip():
        print("warning: uncommitted changes are NOT deployed (deploying HEAD only)")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "space"
        tar = subprocess.check_output(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT)
        with tarfile.open(fileobj=BytesIO(tar)) as t:
            t.extractall(out, filter="data")
        shutil.copy(out / "infra" / "deploy" / "Dockerfile", out / "Dockerfile")
        (out / "README.md").write_text(SPACE_README, encoding="utf-8")
        api.upload_folder(repo_id=repo_id, repo_type="space", folder_path=str(out),
                          commit_message=f"Deploy {sha}", delete_patterns=["*"])
    print(f"uploaded commit {sha}; build logs: https://huggingface.co/spaces/{repo_id}?logs=build")


if __name__ == "__main__":
    main()
