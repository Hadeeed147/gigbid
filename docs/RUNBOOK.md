# Runbook

## Environments

| | Full stack (grading, viva, evals) | Public demo link (free host) |
|---|---|---|
| Start | `docker compose -f infra/docker-compose.yml --env-file .env up --build` (or `make dev`) | Render free web service built from the root `Dockerfile` (= `infra/render/Dockerfile`) |
| Processes | web (nginx), API, Arq worker, 3 MCP servers over streamable HTTP, GigSim, Postgres+pgvector, Redis, optional Ollama | one container: API (serves the web app, runs the Arq worker in-process), MCP servers in-process, GigSim and Redis on localhost; Postgres on Neon |
| Retrieval | V8 corrective (chosen by `evals/results/rag_eval.csv`) | `lite_bm25`, keyword only (`GIGBID_LITE=1`): no embedding or reranker model is loaded |
| RAM | ~2 GB | peaks around 200 MB under a hard 512 MB limit (measured locally with `docker run --memory=512m`) |

**Why two:** the free host has 512 MB RAM and 0.1 CPU, and the CPU embedding plus reranker models do not fit. The
lite link trades retrieval quality for fitting on it. Measured on the same 360 dev queries: lite_bm25 Recall@5 0.381,
nDCG@10 0.581 vs V8 corrective 0.426 / 0.640 (`evals/results/rag_eval_lite.csv`, `rag_eval.csv`). Claim
verification still runs on the lite link (LLM grader over keyword candidates); if the grader is unavailable every
claim is treated as unsupported and removed, never kept unchecked.

## Secrets

Only from environment variables. `.env.example` lists them; `.env` and `.env.render` are git-ignored. On Render they
are set in the dashboard (Environment → "Add from .env"). Required: `GROQ_API_KEY`, `NEON_DATABASE_URL`, `JWT_SECRET`,
`TOKEN_ENCRYPTION_KEY`, `REVIEWER_EMAIL`, `REVIEWER_PASSWORD`, `MCP_BEARER_TOKEN`, `GIGSIM_ADMIN_KEY`; optional
`LANGSMITH_API_KEY` (tracing), `GITHUB_PERSONAL_ACCESS_TOKEN` (repo ingestion).

## Scheduling

Every minute the worker checks which saved searches are due. Each search has its own interval, never below a floor
per mode (`agent/config.yaml`): **10 minutes in GigSim**, **240 minutes in live Upwork mode**. The live interval is
conservative on purpose: new postings in a niche arrive over hours, a human approves every send anyway, and polling
an official API faster than needed spends rate limit that interactive use needs. Jobs are processed idempotently
(job id + user id keys, idempotency keys on every marketplace write), so a worker restart never double-analyses or
double-submits.

On the free host the service sleeps after 15 minutes without traffic, so scheduled scouting only runs while it is
awake. The first request after sleep takes 30–60 s. The full stack has no such limit.

## Degraded mode drill (viva)

1. `docker compose -f infra/docker-compose.yml stop mcp-marketplace`
2. Within one health probe (2 min, or on the next request) the UI shows "marketplace unavailable"; new work is queued.
3. `docker compose -f infra/docker-compose.yml start mcp-marketplace`; queued work resumes from its checkpoint.

## Crash-and-resume drill (C6)

1. Open a job until its proposal waits for approval.
2. `docker compose -f infra/docker-compose.yml restart api worker`
3. Approve from the UI: the Postgres checkpointer resumes the thread and the proposal is submitted exactly once
   (idempotency key on `submit_proposal`).

## Budgets (open profile, Groq)

Free tier limits seen on 15 Nov 2026: 1,000 requests/day and 8,000 tokens/minute per model (openai/gpt-oss-20b,
openai/gpt-oss-120b, qwen/qwen3.8-27b each have their own bucket). Calls that hit a 429 wait for the `retry-after`
time and retry; small-tier nodes fall back to qwen3.8-27b. Measured per-job cost and latency are in
`evals/results/decision_eval.json`.

## Deploy

* Render: push to `main`; auto-deploy rebuilds the root `Dockerfile`. Health check path `/api/health`.
* The reviewer login and two demo users are seeded on every start (idempotent, `scripts/seed.py`).
* Before deploying, build from a clean tree so ignored files cannot hide a missing input:
  `git archive --format=tar HEAD | docker build -f infra/render/Dockerfile -t gigbid-lite -`
