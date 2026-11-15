#!/usr/bin/env bash
# Container entrypoint: map host secrets, then hand every process to supervisord.
set -euo pipefail
cd /app
mkdir -p data/processed/logs
# The host stores the Neon URL as NEON_DATABASE_URL; the code reads DATABASE_URL.
export DATABASE_URL="${DATABASE_URL:-${NEON_DATABASE_URL:-}}"
if [ -z "$DATABASE_URL" ]; then echo "DATABASE_URL / NEON_DATABASE_URL is not set" >&2; exit 1; fi
export API_PUBLIC_URL="${API_PUBLIC_URL:-${SPACE_HOST:+https://$SPACE_HOST}}"
export WEB_PUBLIC_URL="${WEB_PUBLIC_URL:-$API_PUBLIC_URL}"
exec supervisord -n -c infra/deploy/supervisord.conf
