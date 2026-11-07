#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

DC="docker compose"
docker compose version >/dev/null 2>&1 || DC="docker-compose"

$DC up -d redis
.venv/bin/celery -A config worker -l info
