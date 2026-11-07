from django.urls import path

from support.apis import AdminTicketListApi, TicketCloseApi, TicketDetailApi, TicketListCreateApi, TicketMessageApi

urlpatterns = [
    path("", TicketListCreateApi.as_view(), name="ticket-list-create"),
    path("<int:ticket_id>/", TicketDetailApi.as_view(), name="ticket-detail"),
    path("<int:ticket_id>/messages/", TicketMessageApi.as_view(), name="ticket-message"),
    path("<int:ticket_id>/close/", TicketCloseApi.as_view(), name="ticket-close"),
    path("admin/", AdminTicketListApi.as_view(), name="admin-ticket-list"),
]
