from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from users.apis import (
    AdminUserDetailApi,
    AdminUserListApi,
    ChangePasswordApi,
    ConfirmPasswordResetApi,
    LoginApi,
    LogoutApi,
    ProfileApi,
    RegisterApi,
    RequestPasswordResetApi,
    VerifyPasswordResetApi,
)

urlpatterns = [
    path("register/", RegisterApi.as_view(), name="register"),
    path("login/", LoginApi.as_view(), name="login"),
    path("logout/", LogoutApi.as_view(), name="logout"),
    path("me/", ProfileApi.as_view(), name="profile"),
    path("change-password/", ChangePasswordApi.as_view(), name="change-password"),
    path("password-reset/request/", RequestPasswordResetApi.as_view(), name="password-reset-request"),
    path("password-reset/verify/", VerifyPasswordResetApi.as_view(), name="password-reset-verify"),
    path("password-reset/confirm/", ConfirmPasswordResetApi.as_view(), name="password-reset-confirm"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("admin/", AdminUserListApi.as_view(), name="admin-user-list"),
    path("admin/<int:user_id>/", AdminUserDetailApi.as_view(), name="admin-user-detail"),
]
