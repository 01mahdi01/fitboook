import logging

from django.conf import settings

from sms import smsir_apis
from sms.smsir_apiclient import SmsDeliveryError, normalize_mobile

logger = logging.getLogger(__name__)

# ponytail: conservative per-request recipient cap; raise it if sms.ir's panel documents a higher limit.
BULK_CHUNK_SIZE = 100


def deliver_sms(*, phones: list[str], message: str) -> int:
    """Send synchronously; returns the delivered-recipient count or raises SmsDeliveryError saying how far it got."""
    mobiles = sorted({normalize_mobile(phone) for phone in phones})
    if not settings.SMSIR_API_KEY:
        logger.warning("SMSIR_API_KEY not set; not sending SMS to %d recipient(s): %s", len(mobiles), message)
        return len(mobiles)
    sent = 0
    for start in range(0, len(mobiles), BULK_CHUNK_SIZE):
        chunk = mobiles[start : start + BULK_CHUNK_SIZE]
        try:
            smsir_apis.send_bulk(mobiles=chunk, message=message)
        except SmsDeliveryError as exc:
            if sent:
                raise SmsDeliveryError(
                    f"{exc.message} Already delivered to {sent} of {len(mobiles)} recipients; the rest were not sent."
                ) from exc
            raise
        sent += len(chunk)
    return sent


def deliver_otp(*, phone: str, code: str) -> None:
    if not settings.SMSIR_API_KEY:
        # Only reveal the code in dev; a misconfigured production must not leak OTPs into logs.
        logger.warning("SMSIR_API_KEY not set; OTP for %s not sent%s", phone, f": {code}" if settings.DEBUG else "")
        return
    smsir_apis.send_verify(
        mobile=normalize_mobile(phone),
        template_id=settings.SMSIR_OTP_TEMPLATE_ID,
        parameters={settings.SMSIR_OTP_PARAMETER_NAME: code},
    )
