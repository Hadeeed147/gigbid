"""Repo ingestion through the official GitHub MCP server (B1, A5).

Reads a user's public repositories (README + a few top-level code files) with the
GitHub MCP server's read tools, writes them under the user's portfolio folder and
re-indexes incrementally. Read-only token; nothing is written back to GitHub.

Run:  uv run python -m rag.ingest.github <tenant> <github_login>
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from common.config import cfg, env
from rag.ingest.loaders import CODE_EXT, RawItem

USERS = Path(__file__).resolve().parents[2] / "data" / "processed" / "users"


def _text(res) -> str:
    """Tool results arrive as text or content blocks; normalise to a string."""
    if isinstance(res, str):
        return res
    if isinstance(res, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in res)
    return json.dumps(res)


async def _client():
    from langchain_mcp_adapters.client import MultiServerMCPClient
    token = env("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_PERSONAL_ACCESS_TOKEN is not set (read-only token for the GitHub MCP server)")
    client = MultiServerMCPClient({"github": {"transport": "streamable_http", "url": cfg("github.mcp_url"),
                                              "headers": {"Authorization": f"Bearer {token}"}}})
    return {t.name: t for t in await client.get_tools(server_name="github")}


async def fetch_repos(login: str) -> list[dict]:
    tools = await _client()
    found = _text(await tools["search_repositories"].ainvoke({"query": f"user:{login} fork:false", "perPage": 30}))
    try:
        items = json.loads(found).get("items", [])
    except json.JSONDecodeError:
        items = []
    repos = []
    for r in items[: cfg("github.max_repos", 8)]:
        name = r.get("name")
        files: dict[str, str] = {}
        for path in ("README.md", "readme.md"):
            try:
                files["README.md"] = _text(await tools["get_file_contents"].ainvoke(
                    {"owner": login, "repo": name, "path": path}))
                break
            except Exception:  # noqa: BLE001 - repo without a README
                continue
        try:
            listing = json.loads(_text(await tools["get_file_contents"].ainvoke({"owner": login, "repo": name, "path": "/"})))
        except Exception:  # noqa: BLE001
            listing = []
        code = [f for f in listing if isinstance(f, dict) and f.get("type") == "file"
                and Path(f.get("name", "")).suffix in CODE_EXT][: cfg("github.max_code_files", 4)]
        for f in code:
            try:
                files[f["name"]] = _text(await tools["get_file_contents"].ainvoke(
                    {"owner": login, "repo": name, "path": f["path"]}))[:20000]
            except Exception:  # noqa: BLE001
                continue
        repos.append({"name": name, "description": r.get("description") or "", "url": r.get("html_url"),
                      "updated": (r.get("updated_at") or "")[:10], "files": files})
    return repos


def save_and_index(tenant: str, repos: list[dict]) -> int:
    from rag.retriever import get_store
    store = get_store()
    n = 0
    for r in repos:
        slug = re.sub(r"[^a-zA-Z0-9_-]", "-", r["name"])
        rdir = USERS / tenant / "repos" / slug
        rdir.mkdir(parents=True, exist_ok=True)
        meta = {"project_id": f"{tenant}:gh:{slug}", "persona": tenant, "year": r["updated"][:4], "source": "github",
                "url": r["url"]}
        (rdir / ".gigbid.json").write_text(json.dumps(meta), encoding="utf-8")
        for fname, content in r["files"].items():
            (rdir / fname).write_text(content, encoding="utf-8")
            kind = "readme" if fname.lower() == "readme.md" else "code"
            iid = f"{tenant}:{kind}:{slug}" + ("" if kind == "readme" else f":{fname}")
            n += store.add_item(RawItem(item_id=iid, type=kind, tenant=tenant, text=content,
                                        title=f"{slug} README" if kind == "readme" else f"{slug}/{fname}",
                                        project_id=meta["project_id"], date=r["updated"], source="github"))
    return n


async def ingest(tenant: str, login: str) -> dict:
    repos = await fetch_repos(login)
    chunks = save_and_index(tenant, repos)
    return {"repos": len(repos), "chunks_indexed": chunks}


if __name__ == "__main__":
    print(asyncio.run(ingest(sys.argv[1], sys.argv[2])))
