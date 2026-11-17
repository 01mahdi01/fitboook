"""Public URL routes for the Expo Updates protocol.

Included in the project as:

    path("api/updates/", include("ota.urls"))

which yields exactly:

    GET /api/updates/manifest
    GET /api/updates/assets

``app.json`` in the Expo client must point at the manifest URL. The trailing
slash variants are accepted for human/browser convenience; the Expo client
always calls the canonical no-slash URLs generated in the manifest.
"""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "ota"

urlpatterns = [
    path("manifest", views.manifest, name="manifest"),
    path("manifest/", views.manifest, name="manifest-slash"),
    path("assets", views.asset, name="assets"),
    path("assets/", views.asset, name="assets-slash"),
]
