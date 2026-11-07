from django.contrib.auth.backends import ModelBackend

from users.models import BaseUser


class PhoneBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        phone = username or kwargs.get("phone")
        if not phone:
            return None
        try:
            user = BaseUser.objects.get(phone=phone)
        except BaseUser.DoesNotExist:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
