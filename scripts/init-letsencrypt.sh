#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

DOMAIN="api.fitboook.ir"
EMAIL="${LETSENCRYPT_EMAIL:-}"

DC="docker compose"
docker compose version >/dev/null 2>&1 || DC="docker-compose"

echo "Checking $DOMAIN resolves to this server..."
RESOLVED=$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1 || true)
if [ -z "$RESOLVED" ]; then
  echo "ERROR: $DOMAIN does not resolve yet. Point its A record at this server's IP and wait for DNS to propagate before running this script." >&2
  exit 1
fi
echo "$DOMAIN resolves to $RESOLVED"

echo "Creating a dummy self-signed cert so nginx can start..."
$DC -f docker-compose.prod.yml run --rm --entrypoint "\
  sh -c 'mkdir -p /etc/letsencrypt/live/$DOMAIN && \
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout /etc/letsencrypt/live/$DOMAIN/privkey.pem \
    -out /etc/letsencrypt/live/$DOMAIN/fullchain.pem \
    -subj "/CN=localhost"'" certbot

echo "Starting nginx with the dummy cert..."
$DC -f docker-compose.prod.yml up -d nginx

echo "Deleting the dummy cert..."
$DC -f docker-compose.prod.yml run --rm --entrypoint "rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/archive/$DOMAIN /etc/letsencrypt/renewal/$DOMAIN.conf" certbot

echo "Requesting the real certificate from Let's Encrypt..."
EMAIL_ARG="--register-unsafely-without-email"
[ -n "$EMAIL" ] && EMAIL_ARG="--email $EMAIL --no-eff-email"

$DC -f docker-compose.prod.yml run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $EMAIL_ARG \
    -d $DOMAIN \
    --agree-tos \
    --non-interactive" certbot

echo "Reloading nginx with the real certificate..."
$DC -f docker-compose.prod.yml exec nginx nginx -s reload

echo "Done. https://$DOMAIN should now be live."
