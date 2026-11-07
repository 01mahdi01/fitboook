#!/usr/bin/env bash
# Runs ON the server: pulls main, rebuilds web + worker, restarts the stack.
# Normally started by scripts/deploy-remote.sh from your machine — `ssh -A` lends git your GitHub key
# (the server has no key of its own). Running it by hand on the server also works if you ssh'd in with -A.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "Missing .env — copy .env.prod.example to .env and fill it in first." >&2; exit 1; }

SUDO=""
docker info >/dev/null 2>&1 || SUDO="sudo -n"
if $SUDO docker compose version >/dev/null 2>&1; then DC="$SUDO docker compose"; else DC="$SUDO docker-compose"; fi
DC="$DC -f docker-compose.prod.yml"

[ -d .git ] && git pull --ff-only

$DC build web worker
# No `pull`: third-party images (minio:latest, ...) are not upgraded as a side effect of an app deploy.
if ! $DC up -d; then
  # docker-compose v1 + newer Docker: recreating a container fails with KeyError 'ContainerConfig' and leaves
  # the old one stopped and renamed to <hash>_video_application_<svc>_1 — the site is down until this runs.
  echo "compose up failed; removing stale renamed containers and retrying..." >&2
  $SUDO docker ps -aq --filter "name=_video_application_" --filter status=exited | xargs -r $SUDO docker rm
  $DC up -d
fi

$DC ps
echo "Deployed $(git rev-parse --short HEAD 2>/dev/null || echo '(no git)')."
