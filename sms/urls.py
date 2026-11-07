from django.urls import path

from sms.apis import AdminSendSmsApi

urlpatterns = [
    path("admin/send/", AdminSendSmsApi.as_view(), name="admin-send-sms"),
]
