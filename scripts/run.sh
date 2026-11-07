#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

DC="docker compose"
docker compose version >/dev/null 2>&1 || DC="docker-compose"

$DC up -d postgres redis minio
.venv/bin/python manage.py runserver 0.0.0.0:8000
