# GigBid

**A team of LangGraph agents that finds freelance jobs, decides whether they are worth a bid, writes proposals grounded
in the freelancer's real portfolio, and handles client conversations. Nothing leaves the system until a human approves it.**

**Live demo:** https://gigbid-0gsi.onrender.com (free host: the first load after 15 idle minutes takes 30–60 s while
it wakes). Reviewer login details are in the private comment on the Classroom submission.

AI-4016 Agentic AI, Assignment 2 (FAST-NUCES). Course brief: GigBid.

---

## What it does

1. **Scout.** The worker scouts saved searches on a schedule, against GigSim (the marketplace simulator built for this
   project) or live Upwork through the same port.
2. **Analyse in parallel.** For every new job, the Job Analyst, Risk Assessor and Fit Matcher run in parallel. They
   produce a JobSpec, a risk report (scams, planted prompt injections, red flags) and a requirement-to-evidence matrix
   built from the portfolio.
3. **Decide and price.** The graph decides bid or skip and proposes a price from market statistics, the client's spend
   and the user's floor.
4. **Write and check.** The Writer drafts. The claim verifier splits the draft into claims and checks each one against
   retrieved evidence, removing or rewriting unsupported claims. The Critic sends weak drafts back at most twice.
   Compliance Guard checks the marketplace rules.
5. **Human approval.** `interrupt()` stops before anything is sent. The approval screen shows the draft, the evidence
   behind every claim, the risk report, the price rationale and a dry-run preview. You approve, edit (edits are diffed,
   re-checked by Compliance and learned into style memory) or reject with a reason.
6. **Send once.** Only then does the proposal go through the single marketplace port. Idempotency keys mean a retry
   never submits twice or spends Connects twice.

## Architecture

```
React web app ──► FastAPI (SSE streaming, auth, approvals) ──► Arq worker (Redis): scouting, graph runs
                                   │
                   LangGraph bid graph + conversation graph
                   Postgres checkpointer (durable approvals) · LangGraph store (style + outcome memory)
                                   │ MultiServerMCPClient, per-agent tool allowlists
        ┌──────────────────────────┼──────────────────────────┬──────────────────────┐
  Portfolio MCP (read)     Marketplace MCP (read+write)    Workspace MCP        GitHub MCP (official)
  hybrid RAG + verifier    → marketplace port → GigSim     calendar, drafts     repo ingestion
                                     or live Upwork MCP (OAuth 2.1)
```

* Bid graph: [`docs/images/bid_graph.mmd`](docs/images/bid_graph.mmd). Conversation graph:
  [`docs/images/conversation_graph.mmd`](docs/images/conversation_graph.mmd). Both are rendered from the compiled graphs.
* Tools: [`docs/TOOLS.md`](docs/TOOLS.md) (one row per tool: server, read/write, annotations, auth).
* Data: [`docs/DATA_CARD.md`](docs/DATA_CARD.md). Every record is labelled `synthetic` or `kaggle:<file>`.
* Operations: [`docs/RUNBOOK.md`](docs/RUNBOOK.md) covers scheduling, degraded mode, crash-and-resume, budgets and the two deployment modes.

## Results

Every number below is read from a file in [`evals/results/`](evals/results/). The script that regenerates it is named
beside each table.

### Retrieval: RAG variants (dev set, 360 queries, 120 per persona)

`uv run python -m evals.runners.rag_eval --per-persona 120` → `evals/results/rag_eval.csv`

| Variant | Recall@5 | MRR | nDCG@10 | p50 latency (s) | p95 latency (s) |
|---|---|---|---|---|---|
| V0 naive dense (baseline) | 0.346 | 0.514 | 0.514 | 0.018 | 0.178 |
| V1 requirement decomposition | 0.320 | 0.506 | 0.527 | 0.046 | 0.412 |
| V2 hybrid (dense + BM25, RRF) | 0.377 | 0.567 | 0.574 | 0.044 | 0.426 |
| V3 + cross-encoder rerank | 0.373 | 0.564 | 0.582 | 6.023 | 18.690 |
| V4 + outcome-aware ranking | 0.418 | 0.575 | 0.636 | 5.900 | 21.325 |
| **V8 corrective (shipped)** | **0.426** | **0.590** | **0.640** | 6.350 | 12.837 |
| lite_bm25 (public free-host link only) | 0.381 | 0.564 | 0.581 | 0.000 | 0.002 |

**What ships:** V8 corrective. It has the best Recall@5 (+8.0 points over V0) and the best nDCG@10 (+12.6 points). Its p95
latency was also lower than V4's (12.8 s vs 21.3 s). Requirement decomposition on its own (V1) did not help: it lowered recall versus V0. The gains come from
hybrid retrieval plus outcome-aware ranking.

**The public link runs `lite_bm25`.** The free host has 512 MB RAM and the embedding plus reranker models do not fit.
On the same 360 queries it gives up 4.5 Recall@5 points and 5.9 nDCG@10 points against V8, while still beating the
dense V0 baseline. `docker compose up`, the evals and the viva demo run the full V8 system.
(`evals/results/rag_eval_lite.csv`)

### Agent decisions, injections and tools

Results for the bid-or-skip decision, the injection attack-success rate before and after defences, and the tool
granularity study are written to `evals/results/decision_eval.json`, `injection_eval.json` and `tool_study.json` by:

```bash
GIGBID_LLM_CACHE=1 uv run python -m evals.runners.decision_eval --per-persona 10 --outcomes
GIGBID_LLM_CACHE=1 uv run python -m evals.runners.injection_eval --max-planted-per-persona 3 --extra-per-persona 1
GIGBID_PROFILE=open_alt uv run python -m evals.runners.tool_study
```

They run on Groq's free tier (8,000 tokens/minute per model; one analysed job costs about 13k tokens), so they use
subsets of the dev set. Each file records its sample size, and the report quotes only what these files contain.

## Run it

```bash
cp .env.example .env            # fill GROQ_API_KEY, JWT_SECRET, TOKEN_ENCRYPTION_KEY, REVIEWER_PASSWORD, ...
make up                         # docker compose: web :8080, API :8000, worker, 3 MCP servers, GigSim, Postgres, Redis
make seed                       # reviewer login + demo users
make test                       # unit, integration and MCP contract tests (no API key needed)
make eval                       # retrieval + decision metrics -> evals/results/
```

Models: the **open** profile (required, used everywhere) runs open-weight models on Groq: `openai/gpt-oss-20b` for
small nodes, `openai/gpt-oss-120b` for Writer, Critic and Liaison, and `qwen/qwen3.8-27b` as fallback. Embeddings
(`BAAI/bge-small-en-v1.5`) and the reranker (`ms-marco-MiniLM-L-6-v2`) are open models on CPU. A `local` profile runs
everything through Ollama.

## Repository map

```
agent/        graphs, nodes, typed state, Pydantic hand-offs, prompts/, memory, MCP client, marketplace port
apps/api      FastAPI: auth, inbox, proposals, approvals, SSE, settings
apps/web      React app: inbox, job detail, proposal studio (evidence on hover), pipeline, messages, runs, analytics
mcp_servers/  portfolio, marketplace (GigSim + live adapter), workspace, each with tests
rag/          loaders, chunkers, hybrid index, variants V0–V4, V8, lite_bm25, claim verifier
gigsim/       marketplace simulator (frozen; CI checks its checksum)
evals/        runners/ and results/ (every number in this README and the report)
infra/        docker-compose, the full single-container image, the lite free-host image
```

## Safety and platform respect

GigBid never sends anything without your approval. It never moves contact or payment off the platform, never claims
experience the portfolio does not support, and never promises results. Job posts and client messages are treated as
untrusted data: they are delimited, never followed as instructions, pre-filtered for injection patterns, and checked
again by Compliance Guard before the approval screen. The planted-injection jobs in the dev set test all of this.
