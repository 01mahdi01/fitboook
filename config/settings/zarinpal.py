from config.env import env

ZARINPAL_MERCHANT_ID = env("ZARINPAL_MERCHANT_ID", default="")

# Fixed public origin used to build the ZarinPal callback_url — deliberately NOT derived from the incoming
# request (request.scheme/get_host()), since that could still be the bare IP/port 8000 if someone calls the
# purchase endpoint directly instead of through the domain, and ZarinPal only trusts the exact domain
# registered in its merchant panel.
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="http://localhost:8000")
