#!/usr/bin/env bash
# Lite entrypoint: Redis + GigSim in the background, seed once, API (with the worker) in front.
set -euo pipefail
cd /app
mkdir -p data/processed/logs
export DATABASE_URL="${NEON_DATABASE_URL:-${DATABASE_URL:-}}"
[ -n "$DATABASE_URL" ] || { echo "NEON_DATABASE_URL is not set" >&2; exit 1; }
PUBLIC="${RENDER_EXTERNAL_URL:-}"
export API_PUBLIC_URL="${PUBLIC:-${API_PUBLIC_URL:-}}" WEB_PUBLIC_URL="${PUBLIC:-${WEB_PUBLIC_URL:-}}"

redis-server --port 6379 --bind 127.0.0.1 --save "" --appendonly no --maxmemory 32mb --daemonize yes
uvicorn gigsim.server:app --host 127.0.0.1 --port 8100 --log-level warning &
for i in $(seq 1 30); do curl -fs http://127.0.0.1:8100/health >/dev/null && break; sleep 1; done
python -m scripts.seed || echo "seed failed (continuing)"
exec uvicorn apps.api.main:app --host 0.0.0.0 --port "${PORT:-10000}" --proxy-headers --forwarded-allow-ips='*'
