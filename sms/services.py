import secrets

from django.core.cache import cache

from config.errors import ApplicationError
from sms import smsir_services
from users.models import BaseUser

OTP_LENGTH = 6
OTP_TTL_SECONDS = 2 * 60
OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_MAX_ATTEMPTS = 5


def send_sms(*, phones: list[str], message: str) -> int:
    """Entry point for any app that needs to text someone. Sends now (with retries) and returns the recipient
    count, or raises SmsDeliveryError (HTTP 502 via the exception handler) with the failure reason."""
    return smsir_services.deliver_sms(phones=phones, message=message)


def send_sms_to_users(*, message: str, user_ids: list[int] | None = None) -> int:
    """user_ids=None means every active user. Returns the recipient count."""
    users = BaseUser.objects.filter(is_active=True)
    if user_ids is not None:
        users = users.filter(id__in=user_ids)
    phones = list(users.values_list("phone", flat=True))
    if not phones:
        raise ApplicationError("No matching active users.")
    return send_sms(phones=phones, message=message)


def _otp_key(kind: str, purpose: str, phone: str) -> str:
    return f"otp:{kind}:{purpose}:{phone}"


def request_otp(*, phone: str, purpose: str) -> bool:
    """Send a fresh code for `purpose` (e.g. "password_reset", "login"). Returns False while in resend cooldown."""
    if not cache.add(_otp_key("cooldown", purpose, phone), 1, timeout=OTP_RESEND_COOLDOWN_SECONDS):
        return False
    code = f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"
    cache.set(_otp_key("code", purpose, phone), code, timeout=OTP_TTL_SECONDS)
    cache.delete(_otp_key("attempts", purpose, phone))
    try:
        smsir_services.deliver_otp(phone=phone, code=code)
    except ApplicationError:
        # Nothing reached the user: drop the code and cooldown so they can retry right away.
        cache.delete_many([_otp_key(kind, purpose, phone) for kind in ("cooldown", "code")])
        raise
    return True


def verify_otp(*, phone: str, purpose: str, code: str) -> None:
    """Consume the code or raise. Burns the code after OTP_MAX_ATTEMPTS wrong guesses."""
    code_key = _otp_key("code", purpose, phone)
    attempts_key = _otp_key("attempts", purpose, phone)
    expected = cache.get(code_key)
    if expected is None:
        raise ApplicationError("Invalid or expired code.")
    cache.add(attempts_key, 0, timeout=OTP_TTL_SECONDS)
    if cache.incr(attempts_key) > OTP_MAX_ATTEMPTS:
        cache.delete_many([code_key, attempts_key])
        raise ApplicationError("Too many attempts. Request a new code.", status_code=429)
    if not secrets.compare_digest(expected, code):
        raise ApplicationError("Invalid or expired code.")
    cache.delete_many([code_key, attempts_key])
