import secrets

from django.core.cache import cache

from config.errors import ApplicationError
from sms.services import request_otp, verify_otp
from users.models import BaseUser

PASSWORD_RESET_OTP_PURPOSE = "password_reset"
PASSWORD_RESET_TOKEN_TTL_SECONDS = 10 * 60


def register(*, phone: str, password: str, full_name: str = "", email: str = "") -> BaseUser:
    return BaseUser.objects.create_user(phone=phone, password=password, full_name=full_name, email=email)


def revoke_all_sessions(*, user: BaseUser) -> None:
    user.token_version += 1
    user.save(update_fields=["token_version"])


def change_password(*, user: BaseUser, old_password: str, new_password: str) -> None:
    if not user.check_password(old_password):
        raise ApplicationError("Old password is incorrect.")
    user.set_password(new_password)
    user.token_version += 1
    user.save(update_fields=["password", "token_version"])


def _reset_token_key(token: str) -> str:
    return f"password_reset_token:{token}"


def request_password_reset(*, phone: str) -> None:
    # Unregistered phones and resend-cooldown hits return the same silent 204, so callers can't enumerate users.
    if BaseUser.objects.filter(phone=phone, is_active=True).exists():
        request_otp(phone=phone, purpose=PASSWORD_RESET_OTP_PURPOSE)


def verify_password_reset_code(*, phone: str, code: str) -> str:
    """Exchange a valid SMS code for a short-lived single-use reset token."""
    verify_otp(phone=phone, purpose=PASSWORD_RESET_OTP_PURPOSE, code=code)
    token = secrets.token_urlsafe(32)
    cache.set(_reset_token_key(token), phone, timeout=PASSWORD_RESET_TOKEN_TTL_SECONDS)
    return token


def reset_password(*, reset_token: str, new_password: str) -> None:
    token_key = _reset_token_key(reset_token)
    phone = cache.get(token_key)
    user = BaseUser.objects.filter(phone=phone, is_active=True).first() if phone else None
    if user is None:
        raise ApplicationError("Invalid or expired reset token.")
    cache.delete(token_key)
    user.set_password(new_password)
    user.token_version += 1
    user.save(update_fields=["password", "token_version"])
