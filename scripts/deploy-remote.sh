#!/usr/bin/env bash
# Run from YOUR machine: pushes main to GitHub, deploys it on production, then health-checks the API.
set -euo pipefail
cd "$(dirname "$0")/.."

SERVER="${DEPLOY_SERVER:-ubuntu@45.135.242.163}"
APP_DIR="${DEPLOY_DIR:-video_application}"
HEALTH_URL="${HEALTH_URL:-https://api.fitboook.ir/api/schema/}"

[ -z "$(git status --porcelain)" ] || { echo "Uncommitted changes — commit them first." >&2; exit 1; }
[ "$(git branch --show-current)" = main ] || { echo "Deploy from main only." >&2; exit 1; }

git push origin main
# Pull before running deploy.sh, so the server always runs the newest version of the deploy script itself.
ssh -A "$SERVER" "cd $APP_DIR && git pull --ff-only && scripts/deploy.sh"

code=000
for _ in $(seq 1 12); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH_URL" || true)
  [ "$code" = 200 ] && { echo "Healthy: $HEALTH_URL"; exit 0; }
  sleep 5
done
echo "Health check failed: $HEALTH_URL -> $code. Check: ssh $SERVER 'cd $APP_DIR && sudo docker-compose -f docker-compose.prod.yml logs --tail 50 web'" >&2
exit 1
