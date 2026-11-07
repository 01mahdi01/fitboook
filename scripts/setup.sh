#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || cp .env.example .env

python3 -m venv .venv
.venv/bin/pip install -q -r requirements/local.txt

DC="docker compose"
docker compose version >/dev/null 2>&1 || DC="docker-compose"

$DC up -d postgres redis minio

echo "Waiting for postgres..."
until $DC exec -T postgres pg_isready -U "${POSTGRES_USER:-course_platform}" >/dev/null 2>&1; do
  sleep 1
done

.venv/bin/python manage.py migrate

echo "Setup done. Run ./scripts/run.sh to start the dev server."
