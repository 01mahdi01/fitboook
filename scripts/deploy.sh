#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "Missing .env — copy .env.prod.example to .env and fill it in first." >&2; exit 1; }

DC="docker compose"
docker compose version >/dev/null 2>&1 || DC="docker-compose"

$DC -f docker-compose.prod.yml pull --ignore-pull-failures || true
$DC -f docker-compose.prod.yml build
$DC -f docker-compose.prod.yml up -d

echo "Deployed. Tail logs with: $DC -f docker-compose.prod.yml logs -f web"
