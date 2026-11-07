import requests
from django.conf import settings

from config.errors import ApplicationError

BASE_URL = "https://api.zarinpal.com/pg/v4/payment"
STARTPAY_URL = "https://www.zarinpal.com/pg/StartPay"


def _post(path: str, payload: dict) -> dict:
    response = requests.post(f"{BASE_URL}/{path}", json=payload, timeout=10)
    try:
        data = response.json()
    except ValueError:
        response.raise_for_status()
        raise ApplicationError("ZarinPal returned an unexpected response.")

    if not response.ok:
        message = (data.get("errors") or {}).get("message", "Unknown ZarinPal error.")
        raise ApplicationError(f"ZarinPal error: {message}")

    return data


def request_payment(*, amount: int, description: str, callback_url: str, mobile: str = "", email: str = "") -> dict:
    metadata = {}
    if mobile:
        metadata["mobile"] = mobile
    if email:
        metadata["email"] = email

    payload = {
        "merchant_id": settings.ZARINPAL_MERCHANT_ID,
        "amount": amount,
        "description": description,
        "callback_url": callback_url,
    }
    if metadata:
        payload["metadata"] = metadata

    return _post("request.json", payload)


def verify_payment(*, amount: int, authority: str) -> dict:
    return _post(
        "verify.json",
        {
            "merchant_id": settings.ZARINPAL_MERCHANT_ID,
            "amount": amount,
            "authority": authority,
        },
    )
