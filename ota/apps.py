"""Django app configuration for the Expo OTA app."""

from __future__ import annotations

from django.apps import AppConfig


class OtaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ota"
    verbose_name = "Expo OTA updates"
