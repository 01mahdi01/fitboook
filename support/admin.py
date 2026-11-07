from django.contrib import admin

from support.models import Ticket, TicketMessage


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "subject", "status", "created_at", "updated_at"]
    list_filter = ["status"]
    search_fields = ["user__phone", "user__email", "subject"]


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ["id", "ticket", "sender", "is_admin_reply", "created_at"]
    list_filter = ["is_admin_reply"]
