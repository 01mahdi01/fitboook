from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken


def issue_tokens(user) -> dict:
    refresh = RefreshToken.for_user(user)
    refresh["tv"] = user.token_version
    access = refresh.access_token
    access["tv"] = user.token_version
    return {"refresh": str(refresh), "access": str(access)}


class VersionedJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if validated_token.get("tv") != user.token_version:
            raise AuthenticationFailed("Token has been revoked.")
        return user


class VersionedRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        refresh = RefreshToken(attrs["refresh"])
        user_id = refresh["user_id"]

        from users.models import BaseUser

        user = BaseUser.objects.get(pk=user_id)
        if refresh.get("tv") != user.token_version:
            raise AuthenticationFailed("Token has been revoked.")
        return data
