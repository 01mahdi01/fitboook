from config.env import env
from config.django.base import *  # noqa

DEBUG = False

SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS if host != "*"]

# Defaults permissive (True) so a fresh deploy isn't silently unreachable from any frontend before a real
# domain is known. Once you have a real frontend origin, set CORS_ALLOW_ALL_ORIGINS=False and list it in
# CORS_ALLOWED_ORIGINS instead — leaving this True in a real production launch defeats the point of CORS.
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=True)
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT

# nginx terminates TLS and forwards this header; without it Django can't tell the original request was
# HTTPS (it only sees the plain-HTTP hop from nginx), so request.is_secure()/request.scheme would be wrong —
# breaking SECURE_SSL_REDIRECT and the ZarinPal callback_url built from request.scheme.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
