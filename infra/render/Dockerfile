# Lite image for a 512 MB free host (Render free web service). See docs/RUNBOOK.md.
# Differences from the full stack (infra/docker-compose.yml, infra/deploy/Dockerfile):
#   * GIGBID_LITE=1   retrieval = lite_bm25 keyword search; no embedding/reranker model is loaded
#                     (measured cost: evals/results/rag_eval_lite.csv vs rag_eval.csv)
#   * MCP servers run in-process (same FastMCP servers, in-memory sessions)
#   * the Arq worker runs inside the API process; Redis runs in the container
#   * GigSim runs in the container on localhost; Postgres + pgvector are external (Neon)
# Build context = repo root:  docker build -f infra/render/Dockerfile .

FROM node:22-alpine AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
ENV VITE_API_URL=""
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends redis-server curl \
    && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir uv==0.8.17
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never PATH=/app/.venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
COPY --from=web /web/dist /app/web_dist

ENV GIGBID_LITE=1 GIGBID_MCP_TRANSPORT=inprocess GIGBID_INPROCESS_WORKER=1 WEB_DIST=/app/web_dist \
    REDIS_URL=redis://127.0.0.1:6379/0 GIGSIM_URL=http://127.0.0.1:8100 \
    GIGSIM_DB=/app/data/processed/gigsim.sqlite GIGBID_PROFILE=open MARKETPLACE_MODE=gigsim \
    MALLOC_ARENA_MAX=2
EXPOSE 10000
CMD ["bash", "infra/render/start.sh"]
