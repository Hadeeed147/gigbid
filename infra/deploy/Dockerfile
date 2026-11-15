# Single-container deployment for a free host (Hugging Face Docker Space, 16 GB RAM, no GPU).
# One image runs what docker-compose runs as separate services: web (served by the API),
# API, Arq worker, the three MCP servers (streamable HTTP, bearer auth), GigSim and Redis.
# Postgres (+pgvector) is external (Neon) via DATABASE_URL so checkpoints and users survive
# restarts. LLMs come from Groq (open profile: open-weight models on a hosted provider).
# Build context = repo root:  docker build -f infra/deploy/Dockerfile .

FROM node:22-alpine AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
ENV VITE_API_URL=""
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends redis-server supervisor curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.8.17 \
    && useradd -m -u 1000 user && mkdir /app && chown user:user /app
USER user
ENV HOME=/home/user PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never FASTEMBED_CACHE_PATH=/home/user/models PATH=/app/.venv/bin:$PATH
WORKDIR /app

COPY --chown=user pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=user . .
COPY --chown=user --from=web /web/dist /app/web_dist

# Bake the CPU embedding + reranker models and the persona embeddings into the image so a
# cold start (the Space waking up) does not re-download or re-embed anything.
RUN python -c "from rag.index.embed import _embedder, _reranker; _embedder(); _reranker()" \
 && python -c "from rag.retriever import get_store; s=get_store(); [s.structured(t).dense('python api', 3) for t in ('ai_ml','fullstack','data_analyst')]" \
 || true

ENV GIGBID_MCP_TRANSPORT=http WEB_DIST=/app/web_dist REDIS_URL=redis://127.0.0.1:6379/0 \
    GIGSIM_URL=http://127.0.0.1:8100 GIGSIM_DB=/app/data/processed/gigsim.sqlite \
    PORTFOLIO_MCP_URL=http://127.0.0.1:8201/mcp MARKETPLACE_MCP_URL=http://127.0.0.1:8202/mcp \
    WORKSPACE_MCP_URL=http://127.0.0.1:8203/mcp GIGBID_PROFILE=open MARKETPLACE_MODE=gigsim

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD curl -fs http://127.0.0.1:7860/api/health || exit 1
CMD ["bash", "infra/deploy/start.sh"]
