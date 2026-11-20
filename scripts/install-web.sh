#!/usr/bin/env bash
# Install a PWA web build (output of the frontend's `npm run build:web`) into web/, which nginx serves at the
# root of api.fitboook.ir. Usage: scripts/install-web.sh "/path/to/fitboook-web-1.3.1"
# Then commit web/ and run scripts/deploy-remote.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="${1:?usage: scripts/install-web.sh <web-build-dir>}"
[ -f "$SRC/index.html" ] && [ -f "$SRC/service-worker.js" ] || { echo "Not a web build: $SRC" >&2; exit 1; }

rm -rf web
mkdir web
# Source maps would publish the app's source code; the deploy readme isn't part of the site.
rsync -a --exclude '*.map' --exclude 'README-DEPLOY.txt' "$SRC/" web/

# The app shares api.fitboook.ir with Django and MinIO. Its service worker answers every page navigation with
# index.html except /api/ and /video(s)/, which would hijack Django admin and PDF/APK links opened in a tab.
# Widen the denylist so those always reach the server. (Frontend: add the same entries to the Workbox
# navigateFallbackDenylist in the build so this patch becomes a no-op.)
OLD='denylist:[/\/api\//,/\/videos?\//]'
NEW='denylist:[/\/api\//,/\/videos?\//,/^\/(django-admin|static|encrypted-videos|course-covers|course-pdfs|app-releases)(\/|$)/]'
if grep -qF "$OLD" web/service-worker.js; then
  python3 - "$OLD" "$NEW" <<'EOF'
import sys
p = "web/service-worker.js"
s = open(p, encoding="utf-8").read()
open(p, "w", encoding="utf-8").write(s.replace(sys.argv[1], sys.argv[2], 1))
EOF
  echo "service-worker.js: navigation denylist widened."
elif grep -q "django-admin" web/service-worker.js; then
  echo "service-worker.js: denylist already covers django-admin/bucket paths."
else
  echo "service-worker.js: navigation denylist not found — check the new build before deploying." >&2
  exit 1
fi

echo "Installed $(du -sh web | cut -f1) into web/. Commit it and run scripts/deploy-remote.sh."
