from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from users.models import BaseUser


@admin.register(BaseUser)
class BaseUserAdmin(UserAdmin):
    ordering = ["phone"]
    list_display = ["phone", "email", "full_name", "is_active", "is_staff", "created_at"]
    search_fields = ["phone", "email", "full_name"]
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("Personal info", {"fields": ("full_name", "email")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login",)}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("phone", "password1", "password2")}),
    )
