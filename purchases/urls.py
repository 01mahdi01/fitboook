from django.urls import path

from purchases.apis import (
    AdminPurchaseListApi,
    AdminUserPurchasesApi,
    FinancialReportApi,
    MyPurchasesApi,
    PurchaseCallbackApi,
    PurchaseCourseApi,
)

urlpatterns = [
    path("", PurchaseCourseApi.as_view(), name="purchase-create"),
    path("my/", MyPurchasesApi.as_view(), name="my-purchases"),
    path("callback/", PurchaseCallbackApi.as_view(), name="purchase-callback"),
    path("admin/", AdminPurchaseListApi.as_view(), name="admin-purchase-list"),
    path("admin/reports/financial/", FinancialReportApi.as_view(), name="financial-report"),
    path("admin/users/<int:user_id>/", AdminUserPurchasesApi.as_view(), name="admin-user-purchases"),
]
