# GigBid developer commands.  make dev | test | eval | seed | demo | lint
SHELL := bash
UV := uv run
COMPOSE := docker compose -f infra/docker-compose.yml --env-file .env

.PHONY: help dev dev-infra dev-backend web up down test test-unit test-contract test-e2e eval eval-smoke \
        eval-full seed demo lint checks openapi data gigsim-checksum

help:
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

dev: dev-infra seed dev-backend web ## Run everything locally (infra in Docker, apps on the host)

dev-infra: ## Start Postgres (+pgvector) and Redis
	$(COMPOSE) up -d postgres redis

dev-backend: ## Start GigSim, API and worker in the background (logs in data/processed/logs)
	mkdir -p data/processed/logs
	GIGSIM_DB=data/processed/gigsim.sqlite $(UV) uvicorn gigsim.server:app --port 8100 > data/processed/logs/gigsim.log 2>&1 &
	GIGBID_MCP_TRANSPORT=inprocess $(UV) python -m scripts.serve api > data/processed/logs/api.log 2>&1 &
	GIGBID_MCP_TRANSPORT=inprocess $(UV) python -m scripts.serve worker > data/processed/logs/worker.log 2>&1 &

web: ## Web dev server on :5173
	npm --prefix apps/web run dev

up: ## Whole stack in Docker (web :8080, api :8000)
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

seed: ## Create the reviewer login (preloaded persona) and demo users
	$(UV) python -m scripts.seed

data: ## Rebuild the synthetic corpus and import Kaggle postings
	$(UV) --group dev python -m data.generators.build_corpus --seed 7
	$(UV) python -m data.generators.import_kaggle

test: test-unit test-contract ## Unit, integration and contract tests (no API key needed)

test-unit:
	GIGBID_FAKE_LLM=1 $(UV) --group dev pytest tests/unit tests/integration mcp_servers -q

test-contract: ## MCP tool-schema snapshots (UPDATE_SNAPSHOTS=1 to accept intended changes)
	$(UV) --group dev pytest tests/contract -q

test-e2e: ## Playwright (needs `make dev-backend` running with GIGBID_FAKE_LLM=1)
	npm --prefix apps/web run test:e2e

eval: ## Retrieval metrics, decision metrics and a fixed GigSim reply-rate run -> evals/results/*.json
	$(UV) python -m evals.runners.rag_eval --per-persona 120
	GIGBID_LLM_CACHE=1 $(UV) python -m evals.runners.decision_eval --per-persona 40 --outcomes

eval-smoke: ## 30-job smoke eval with thresholds (what CI runs)
	$(UV) python -m evals.runners.smoke

eval-full: eval ## Every study in the report
	GIGBID_LLM_CACHE=1 $(UV) python -m evals.runners.injection_eval
	GIGBID_LLM_CACHE=1 $(UV) python -m evals.runners.tool_study
	GIGBID_LLM_CACHE=1 $(UV) python -m evals.runners.ablation --per-persona 15
	GIGBID_LLM_CACHE=1 $(UV) python -m evals.runners.compare_arch --n 50

demo: ## Scout now for the reviewer and open the web app
	$(UV) python -m scripts.demo

openapi: ## Regenerate the OpenAPI schema and the typed TS client
	$(UV) python -c "import json; from apps.api.main import app; open('apps/api/openapi.json','w').write(json.dumps(app.openapi(), indent=1))"
	npm --prefix apps/web run gen:api

lint: ## Ruff + TypeScript + repository rules
	$(UV) --group dev ruff check .
	npm --prefix apps/web run typecheck
	$(UV) python -m scripts.checks

checks: ## Repository rules CI enforces
	$(UV) python -m scripts.checks

gigsim-checksum: ## Freeze GigSim (run once, deliberately)
	$(UV) python -m scripts.checks --write-gigsim-checksum
