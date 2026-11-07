from django.contrib.auth import authenticate
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.decorators import permission_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from config.pagination import DefaultPagination
from users.auth import issue_tokens
from users.models import BaseUser
from users.services import (
    change_password,
    register,
    request_password_reset,
    reset_password,
    revoke_all_sessions,
    verify_password_reset_code,
)
from users.validators import validate_phone


@permission_classes([AllowAny])
class RegisterApi(APIView):
    class InputRegisterSerializer(serializers.Serializer):
        phone = serializers.CharField(validators=[validate_phone])
        password = serializers.CharField(write_only=True)
        confirm_password = serializers.CharField(write_only=True)
        full_name = serializers.CharField(required=False, allow_blank=True)
        email = serializers.EmailField(required=False, allow_blank=True)

        def validate(self, data):
            if data.get("password") != data.get("confirm_password"):
                raise serializers.ValidationError("Confirm password is not equal to password")
            return data

    class OutputRegisterSerializer(serializers.ModelSerializer):
        class Meta:
            model = BaseUser
            exclude = ["password", "is_staff", "is_superuser", "groups", "user_permissions", "token_version"]

    @extend_schema(
        request=InputRegisterSerializer,
        responses=OutputRegisterSerializer,
        summary="Register a new user",
    )
    def post(self, request):
        serializer = self.InputRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        validated_data.pop("confirm_password")
        user = register(**validated_data)
        return Response(self.OutputRegisterSerializer(user).data)


@permission_classes([AllowAny])
class LoginApi(APIView):
    class InputLoginSerializer(serializers.Serializer):
        phone = serializers.CharField()
        password = serializers.CharField(write_only=True)

    class OutputLoginSerializer(serializers.Serializer):
        access = serializers.CharField()
        refresh = serializers.CharField()

    @extend_schema(
        request=InputLoginSerializer,
        responses=OutputLoginSerializer,
        summary="Log in and receive JWT access/refresh tokens",
    )
    def post(self, request):
        serializer = self.InputLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=serializer.validated_data["phone"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            raise AuthenticationFailed("Invalid credentials.")
        return Response(issue_tokens(user))


class LogoutApi(APIView):
    @extend_schema(summary="Log out; revokes all of the current user's JWTs")
    def post(self, request):
        revoke_all_sessions(user=request.user)
        return Response(status=204)


class ProfileApi(APIView):
    class OutputProfileSerializer(serializers.ModelSerializer):
        class Meta:
            model = BaseUser
            fields = ["id", "phone", "email", "full_name", "created_at"]

    class InputProfileUpdateSerializer(serializers.Serializer):
        full_name = serializers.CharField(required=False, allow_blank=True)
        email = serializers.EmailField(required=False, allow_blank=True)

    @extend_schema(responses=OutputProfileSerializer, summary="Get the current user's profile")
    def get(self, request):
        return Response(self.OutputProfileSerializer(request.user).data)

    @extend_schema(
        request=InputProfileUpdateSerializer, responses=OutputProfileSerializer, summary="Update own profile"
    )
    def patch(self, request):
        serializer = self.InputProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(request.user, field, value)
        request.user.save(update_fields=list(serializer.validated_data.keys()))
        return Response(self.OutputProfileSerializer(request.user).data)


class ChangePasswordApi(APIView):
    class InputChangePasswordSerializer(serializers.Serializer):
        old_password = serializers.CharField(write_only=True)
        new_password = serializers.CharField(write_only=True)
        confirm_password = serializers.CharField(write_only=True)

        def validate(self, data):
            if data["new_password"] != data["confirm_password"]:
                raise serializers.ValidationError("Confirm password is not equal to new password")
            return data

    @extend_schema(
        request=InputChangePasswordSerializer,
        summary="Change own password; revokes all existing sessions",
    )
    def post(self, request):
        serializer = self.InputChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        change_password(
            user=request.user,
            old_password=serializer.validated_data["old_password"],
            new_password=serializer.validated_data["new_password"],
        )
        return Response(status=204)


@permission_classes([AllowAny])
class RequestPasswordResetApi(APIView):
    class InputRequestResetSerializer(serializers.Serializer):
        phone = serializers.CharField(validators=[validate_phone])

    @extend_schema(
        tags=["sms"],
        request=InputRequestResetSerializer,
        summary="Request a password reset code via SMS (valid 2 min, resend after 60s). "
        "Returns 204 for unregistered phones and during resend cooldown; 502 if the SMS provider fails.",
    )
    def post(self, request):
        serializer = self.InputRequestResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_password_reset(phone=serializer.validated_data["phone"])
        return Response(status=204)


@permission_classes([AllowAny])
class VerifyPasswordResetApi(APIView):
    class InputVerifyResetSerializer(serializers.Serializer):
        phone = serializers.CharField(validators=[validate_phone])
        code = serializers.CharField()

    class OutputVerifyResetSerializer(serializers.Serializer):
        reset_token = serializers.CharField()

    @extend_schema(
        tags=["sms"],
        request=InputVerifyResetSerializer,
        responses=OutputVerifyResetSerializer,
        summary="Verify the SMS code; returns a single-use reset_token valid for 10 minutes. "
        "5 wrong codes burn the code (429).",
    )
    def post(self, request):
        serializer = self.InputVerifyResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = verify_password_reset_code(**serializer.validated_data)
        return Response(self.OutputVerifyResetSerializer({"reset_token": token}).data)


@permission_classes([AllowAny])
class ConfirmPasswordResetApi(APIView):
    class InputConfirmResetSerializer(serializers.Serializer):
        reset_token = serializers.CharField()
        new_password = serializers.CharField(write_only=True)
        confirm_password = serializers.CharField(write_only=True)

        def validate(self, data):
            if data["new_password"] != data["confirm_password"]:
                raise serializers.ValidationError("Confirm password is not equal to new password")
            return data

    @extend_schema(
        tags=["sms"],
        request=InputConfirmResetSerializer,
        summary="Set a new password using the reset_token; revokes all existing sessions",
    )
    def post(self, request):
        serializer = self.InputConfirmResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reset_password(
            reset_token=serializer.validated_data["reset_token"],
            new_password=serializer.validated_data["new_password"],
        )
        return Response(status=204)


class AdminUserOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = BaseUser
        fields = ["id", "phone", "email", "full_name", "is_active", "is_staff", "created_at"]


class AdminUserListApi(APIView):
    permission_classes = [IsAdminUser]
    pagination_class = DefaultPagination

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="search", type=str, location=OpenApiParameter.QUERY, required=False,
                description="Case-insensitive match against phone, email, or full name.",
            )
        ],
        responses=AdminUserOutputSerializer(many=True),
        summary="List/search users (admin)",
    )
    def get(self, request):
        users = BaseUser.objects.filter(is_superuser=False).order_by("-created_at")
        search = request.query_params.get("search")
        if search:
            users = users.filter(
                Q(phone__icontains=search) | Q(email__icontains=search) | Q(full_name__icontains=search)
            )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(users, request)
        return paginator.get_paginated_response(AdminUserOutputSerializer(page, many=True).data)


class AdminUserDetailApi(APIView):
    permission_classes = [IsAdminUser]

    class InputUserUpdateSerializer(serializers.Serializer):
        is_active = serializers.BooleanField(required=False)
        is_staff = serializers.BooleanField(required=False)

    @extend_schema(responses=AdminUserOutputSerializer, summary="Get a user (admin)")
    def get(self, request, user_id: int):
        user = get_object_or_404(BaseUser, id=user_id)
        return Response(AdminUserOutputSerializer(user).data)

    @extend_schema(
        request=InputUserUpdateSerializer,
        responses=AdminUserOutputSerializer,
        summary="Activate/deactivate a user, or grant/revoke admin (is_staff) role; "
        "deactivating or revoking admin also revokes their sessions",
    )
    def patch(self, request, user_id: int):
        user = get_object_or_404(BaseUser, id=user_id)
        serializer = self.InputUserUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if "is_staff" in serializer.validated_data:
            user.is_staff = serializer.validated_data["is_staff"]
            user.save(update_fields=["is_staff"])
            if not user.is_staff:
                revoke_all_sessions(user=user)
        if "is_active" in serializer.validated_data:
            user.is_active = serializer.validated_data["is_active"]
            user.save(update_fields=["is_active"])
            if not user.is_active:
                revoke_all_sessions(user=user)
        return Response(AdminUserOutputSerializer(user).data)
