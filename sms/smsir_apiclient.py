import functools
import logging
import time
from typing import Any, Callable

import requests
from django.conf import settings
from requests.models import Response
from rest_framework import status
from sms_ir import SmsIr

from config.errors import ApplicationError

logger = logging.getLogger(__name__)

SUCCESS_STATUS = 1
REQUEST_TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1  # waits 1s, then 2s between attempts


class SmsDeliveryError(ApplicationError):
    status_code = status.HTTP_502_BAD_GATEWAY


class _TimeoutSmsIr(SmsIr):
    """smsir-python calls requests with no timeout and swallows network errors; sends run inside the web
    request, so bound them and let the errors surface to `call()` for retrying."""

    def post(self, url, data):
        return requests.post(url, headers=self._headers, json=data, timeout=REQUEST_TIMEOUT_SECONDS)


@functools.cache
def get_client() -> SmsIr:
    client = _TimeoutSmsIr(settings.SMSIR_API_KEY, settings.SMSIR_LINE_NUMBER)
    # The package attaches its own stdout handler; drop it so logs go through the project's LOGGING once.
    client.logger.handlers.clear()
    return client


def call(send: Callable[[], Response]) -> Any:
    """Run one sms.ir request, retrying transient failures (network errors, timeouts, 5xx).
    sms.ir rejections (no credit, bad line/template...) are not retried, since retrying won't fix them."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = send()
        except requests.RequestException as exc:
            # ponytail: a read timeout after sms.ir already accepted the request gets retried too, so a
            # recipient can rarely get the message twice; chosen over silently not sending.
            error = f"could not reach sms.ir ({exc.__class__.__name__})"
        else:
            if response.status_code < 500:
                return parse_response(response)
            error = f"sms.ir is unavailable (HTTP {response.status_code})"
        logger.warning("sms.ir attempt %d/%d failed: %s", attempt, MAX_ATTEMPTS, error)
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise SmsDeliveryError(f"SMS not sent: {error} after {MAX_ATTEMPTS} attempts.")


def parse_response(response: Response) -> Any:
    """sms.ir wraps every reply as {"status": 1, "message": ..., "data": ...}; any other status is a failure."""
    try:
        body = response.json()
    except ValueError:
        raise SmsDeliveryError(f"SMS not sent: unexpected sms.ir response (HTTP {response.status_code}).")
    if body.get("status") != SUCCESS_STATUS:
        raise SmsDeliveryError(f"SMS not sent: sms.ir says: {body.get('message', 'unknown error')}")
    return body.get("data")


def normalize_mobile(phone: str) -> str:
    """sms.ir expects the local form 09xxxxxxxxx; users may be stored as +98 / 0098 / 98 / 9xxxxxxxxx."""
    phone = phone.lstrip("+")
    if phone.startswith("0098"):
        phone = phone[4:]
    elif phone.startswith("98") and len(phone) == 12:
        phone = phone[2:]
    return phone if phone.startswith("0") else f"0{phone}"
