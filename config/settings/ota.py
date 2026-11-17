from config.env import env

# Expo Updates (OTA) server: the `ota` app. Bundles live on disk at
# <OTA_UPDATES_DIR>/<runtimeVersion>/<timestampMillis>/; in production that's the `ota_updates` docker volume.
OTA_UPDATES_DIR = env("OTA_UPDATES_DIR", default="ota-updates")  # relative = under BASE_DIR

# Public origin for absolute asset URLs in the manifest. Behind nginx this must be the real https domain.
OTA_PUBLIC_BASE_URL = env("OTA_PUBLIC_BASE_URL", default=env("PUBLIC_BASE_URL", default=""))

# Shared secret for the CI/admin API (X-Admin-Key header). Empty = admin API disabled (403).
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
OTA_ADMIN_TOKEN = env("OTA_ADMIN_TOKEN", default="")

OTA_MAX_UPLOAD_BYTES = env.int("OTA_MAX_UPLOAD_BYTES", default=256 * 1024 * 1024)
OTA_MAX_RELEASES = env.int("OTA_MAX_RELEASES", default=20)
# Must match the include in config/urls.py.
OTA_ASSETS_PATH = "/api/updates/assets"
