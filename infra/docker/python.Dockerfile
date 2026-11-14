# One Python image for api, worker, the three MCP servers and GigSim; the
# service's command (docker-compose.yml) selects which process runs.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    FASTEMBED_CACHE_PATH=/models
RUN pip install --no-cache-dir uv==0.8.17
WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
# Bake the open embedding + reranker models into the image (CPU, ONNX) so cold starts are fast.
RUN uv run --no-dev python -c "from rag.index.embed import _embedder, _reranker; _embedder(); _reranker()" || true

EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
