"""R&D question A: does tool granularity change agent behaviour?

40 tasks with a known correct call (evals/datasets/tool_tasks.jsonl), three tool sets:
  fine    : the real MCP tool surface (17 tools, as the servers publish them)
  coarse  : 3 tools (marketplace / portfolio / workspace), each taking action + params
  best    : the fine set with rewritten descriptions (what to use it for, what NOT to use it for, an example)
The model must choose ONE tool call. Scored on tool-selection accuracy, argument
accuracy (required arguments match, normalised) and tokens per task.

Run:  GIGBID_LLM_CACHE=1 uv run python -m evals.runners.tool_study [--make-tasks]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random

from langchain_core.tools import StructuredTool

from common.config import model_spec
from common.llm import _client, _price
from evals.runners.common import DATASETS, mean, provenance, write_results

TASKS = DATASETS / "tool_tasks.jsonl"

# --------------------------------------------------------------------------- tasks
TEMPLATES = [
    ("Find open {cat} jobs that mention {kw}.", "search_jobs", lambda r: {"query": r["kw"], "category": r["cat"]}),
    ("Any new jobs about {kw}? Show me the latest ones.", "search_jobs", lambda r: {"query": r["kw"]}),
    ("Show me the full post for job {job}.", "get_job", lambda r: {"job_id": r["job"]}),
    ("Is client {client} trustworthy? Check their hiring history.", "get_client_history", lambda r: {"client_id": r["client"]}),
    ("How many Connects do I have left?", "get_connects_balance", lambda r: {}),
    ("What is the going hourly rate for {cat} work?", "get_market_stats", lambda r: {"category": r["cat"]}),
    ("What are the current platform rules for submitting proposals?", "get_policy", lambda r: {}),
    ("Do I have any proof in my portfolio that I have done {kw} work?", "search_evidence", lambda r: {"requirement": r["kw"]}),
    ("Open my case study {cs} so I can read it.", "get_case_study", lambda r: {"item_id": r["cs"]}),
    ("Which skills can my portfolio actually back up?", "list_skills", lambda r: {}),
    ("Read the messages in conversation {thread}.", "list_messages", lambda r: {"thread_id": r["thread"]}),
    ("Which clients have written back to me?", "list_threads", lambda r: {}),
    ("When am I free for a 30 minute call in the next few days?", "free_slots", lambda r: {}),
    ("Put a tentative hold on my calendar at {slot} for the client interview.", "create_interview_hold", lambda r: {"start": r["slot"]}),
    ("Show what has happened to my proposals since event {seq}.", "list_events", lambda r: {"after_seq": r["seq"]}),
]
FILL = {"cat": ["Data Analytics", "Web Development", "AI & Machine Learning"],
        "kw": ["dbt", "Celery", "Pinecone", "Stripe webhooks", "Power BI", "LangGraph", "React Native", "A/B testing"],
        "job": ["d-ai_ml-012", "d-fullstack-044", "d-data_analyst-101"], "client": ["c0012", "c0207", "c0350"],
        "cs": ["ai_ml:cs:03", "fullstack:cs:11", "data_analyst:cs:07"], "thread": ["th_4be21a9c0d", "th_77aa0c19e2"],
        "slot": ["2026-11-18T15:00:00+05:00", "2026-11-19T11:30:00+05:00"], "seq": [0, 12, 40]}


def make_tasks(n: int = 40, seed: int = 9) -> None:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        tpl, tool, args = TEMPLATES[i % len(TEMPLATES)]
        vals = {k: rng.choice(v) for k, v in FILL.items()}
        rows.append({"id": i + 1, "task": tpl.format(**vals), "tool": tool, "args": args(vals)})
    TASKS.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} tasks to {TASKS}")


# --------------------------------------------------------------------------- tool sets
async def fine_tools() -> list[dict]:
    from mcp.shared.memory import create_connected_server_and_client_session

    from mcp_servers.marketplace.server import mcp as mk
    from mcp_servers.portfolio.server import mcp as pf
    from mcp_servers.workspace.server import mcp as ws
    out = []
    for srv in (mk, pf, ws):
        async with create_connected_server_and_client_session(srv._mcp_server) as s:
            for t in (await s.list_tools()).tools:
                if t.name in ("create_proposal_draft", "submit_proposal", "send_message", "create_email_draft"):
                    continue   # write tools are never chosen by free-form agents in GigBid
                out.append({"name": t.name, "description": t.description or "", "schema": t.inputSchema})
    return out


BETTER = {
    "search_jobs": "Search OPEN job posts on the marketplace by keywords and/or category. Use for finding or listing jobs. "
                   "Not for reading one known job (use get_job). Example: query='dbt', category='Data Analytics'.",
    "get_job": "Read ONE job post when you already have its job id (e.g. 'd-ai_ml-012').",
    "get_client_history": "A client's public track record (payment verified, spend, hires, ratings) by client id like 'c0012'. "
                          "Use to judge whether a client is trustworthy.",
    "get_connects_balance": "How many Connects the freelancer has left. No arguments.",
    "get_market_stats": "Typical hourly rates (25th/50th/75th percentile) for a job category. Use for 'going rate' questions.",
    "get_policy": "The platform's current rules: Connects pricing, required fields, limits. No arguments.",
    "search_evidence": "Search the freelancer's OWN portfolio for proof of a skill or past work. Use whenever the question "
                       "is 'have I done X' or 'do I have evidence of X'. Pass the skill as `requirement`.",
    "get_case_study": "Read ONE portfolio item in full by its item id (e.g. 'ai_ml:cs:03').",
    "list_skills": "List the skills the portfolio can prove, with counts. No arguments.",
    "list_threads": "List conversations with clients (who has replied). No arguments.",
    "list_messages": "Read the messages inside ONE conversation, by thread id (e.g. 'th_4be21a9c0d').",
    "list_events": "Proposal status changes (viewed, replied, hired, lost) after a sequence number `after_seq`.",
    "free_slots": "Find free times in the freelancer's calendar for calls. Optional days_ahead, duration_minutes.",
    "create_interview_hold": "Put a TENTATIVE calendar hold at an exact ISO start time (from free_slots).",
}


def best_tools(fine: list[dict]) -> list[dict]:
    return [{**t, "description": BETTER.get(t["name"], t["description"])} for t in fine]


def coarse_tools() -> list[dict]:
    def tool(name, actions, desc):
        return {"name": name, "description": desc,
                "schema": {"type": "object", "required": ["action"],
                           "properties": {"action": {"type": "string", "enum": actions},
                                          "params": {"type": "object", "description": "Arguments for the action"}}}}
    return [
        tool("marketplace", ["search_jobs", "get_job", "get_client_history", "get_connects_balance", "get_market_stats",
                             "get_policy", "list_threads", "list_messages", "list_events"],
             "Everything on the marketplace: jobs, clients, Connects, rates, rules, conversations, events."),
        tool("portfolio", ["search_evidence", "get_case_study", "list_skills"], "The freelancer's own portfolio."),
        tool("workspace", ["free_slots", "create_interview_hold"], "Calendar: free slots and interview holds."),
    ]


def to_lc(tools: list[dict]) -> list[StructuredTool]:
    async def noop(**kw):
        return "ok"
    return [StructuredTool(name=t["name"], description=t["description"], args_schema=t["schema"], coroutine=noop)
            for t in tools]


# --------------------------------------------------------------------------- scoring
def norm(v):
    return str(v).strip().lower()


def score_call(call: dict | None, task: dict, coarse: bool) -> tuple[bool, bool]:
    if not call:
        return False, False
    name, args = call["name"], call.get("args") or {}
    if coarse:
        name = args.get("action", "")
        args = args.get("params") or {}
    if name != task["tool"]:
        return False, False
    ok_args = all(k in args and (norm(task["args"][k]) in norm(args[k]) or norm(args[k]) in norm(task["args"][k]))
                  for k in task["args"])
    return True, ok_args


def run_set(name: str, tools: list[dict], tasks: list[dict]) -> dict:
    spec = model_spec("intent")
    llm = _client(spec).bind_tools(to_lc(tools), tool_choice="required")
    pin, pout = _price(spec["provider"], spec["model"])
    rows = []
    for t in tasks:
        try:
            msg = llm.invoke([("system", "You help a freelancer. Call exactly one tool to do what they ask."),
                              ("user", t["task"])])
            call = msg.tool_calls[0] if msg.tool_calls else None
            u = msg.usage_metadata or {}
            tok = u.get("input_tokens", 0) + u.get("output_tokens", 0)
            usd = (u.get("input_tokens", 0) * pin + u.get("output_tokens", 0) * pout) / 1e6
        except Exception as e:  # noqa: BLE001
            call, tok, usd = None, None, None
            print("error", t["id"], str(e)[:120])
        sel, arg = score_call(call, t, name == "coarse")
        rows.append({"id": t["id"], "expected": t["tool"], "got": call, "tool_ok": sel, "args_ok": arg, "tokens": tok,
                     "usd": usd})
    return {"tool_selection_accuracy": mean(r["tool_ok"] for r in rows),
            "argument_accuracy": mean(r["args_ok"] for r in rows), "tokens_per_task": mean(r["tokens"] for r in rows),
            "n_tools": len(tools), "model": spec["model"], "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-tasks", action="store_true")
    a = ap.parse_args()
    if a.make_tasks or not TASKS.exists():
        make_tasks()
    tasks = [json.loads(x) for x in TASKS.read_text(encoding="utf-8").splitlines() if x]
    fine = asyncio.run(fine_tools())
    res = {n: run_set(n, ts, tasks) for n, ts in (("fine", fine), ("coarse", coarse_tools()), ("best", best_tools(fine)))}
    out = {"provenance": provenance({"n_tasks": len(tasks)}),
           "summary": {k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in res.items()},
           "rows": {k: v["rows"] for k, v in res.items()}}
    p = write_results("tool_study", out)
    print(json.dumps(out["summary"], indent=1))
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
