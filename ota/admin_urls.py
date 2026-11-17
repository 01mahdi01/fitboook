"""Admin/CI JSON API routes.

Included in the project as:

    path("api/admin/updates/", include("ota.admin_urls"))

which yields:

    GET    /api/admin/updates/                        list releases
    POST   /api/admin/updates/publish/                publish a zipped export
    POST   /api/admin/updates/<id>/activate/          serve this release again
    POST   /api/admin/updates/<id>/deactivate/        roll back to the previous release
    GET    /api/admin/updates/settings/               read the kill switch
    POST   /api/admin/updates/settings/               toggle the kill switch

All endpoints require either the ``X-Admin-Key`` header (``OTA_ADMIN_TOKEN``)
or an authenticated Django staff user.
"""

from __future__ import annotations

from django.urls import path

from . import admin_views

app_name = "ota_admin"

urlpatterns = [
    path("", admin_views.release_list, name="release-list"),
    path("publish/", admin_views.publish, name="publish"),
    path("<int:release_id>/activate/", admin_views.activate, name="activate"),
    path("<int:release_id>/deactivate/", admin_views.deactivate, name="deactivate"),
    path("settings/", admin_views.settings_view, name="settings"),
]
