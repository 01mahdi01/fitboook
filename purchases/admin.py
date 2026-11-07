from django.contrib import admin

from purchases.models import Purchase


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ["user", "course", "amount", "status", "paid_at", "created_at"]
    list_filter = ["status", "course"]
    search_fields = ["user__phone", "user__email", "ref_id", "authority"]
    readonly_fields = ["authority", "ref_id", "paid_at", "created_at"]
