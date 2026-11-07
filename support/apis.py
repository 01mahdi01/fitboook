from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from config.pagination import DefaultPagination
from support.models import Ticket, TicketMessage
from support.services import add_message, close_ticket, create_ticket, get_ticket_for_user


class _TicketMessageOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketMessage
        fields = ["id", "sender", "is_admin_reply", "message", "created_at"]


class _TicketOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ["id", "user", "subject", "status", "created_at", "updated_at"]


class _TicketDetailOutputSerializer(_TicketOutputSerializer):
    messages = _TicketMessageOutputSerializer(many=True, read_only=True)

    class Meta(_TicketOutputSerializer.Meta):
        fields = _TicketOutputSerializer.Meta.fields + ["messages"]


class TicketListCreateApi(APIView):
    class InputCreateTicketSerializer(serializers.Serializer):
        subject = serializers.CharField(max_length=255)
        message = serializers.CharField()

    @extend_schema(responses=_TicketOutputSerializer(many=True), summary="List the current user's tickets")
    def get(self, request):
        tickets = Ticket.objects.filter(user=request.user)
        return Response(_TicketOutputSerializer(tickets, many=True).data)

    @extend_schema(
        request=InputCreateTicketSerializer,
        responses=_TicketDetailOutputSerializer,
        summary="Open a new support ticket",
    )
    def post(self, request):
        serializer = self.InputCreateTicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = create_ticket(user=request.user, **serializer.validated_data)
        return Response(_TicketDetailOutputSerializer(ticket).data)


class TicketDetailApi(APIView):
    @extend_schema(
        responses=_TicketDetailOutputSerializer,
        summary="Get a ticket and its messages (owner or admin)",
    )
    def get(self, request, ticket_id: int):
        ticket = get_ticket_for_user(user=request.user, ticket_id=ticket_id)
        return Response(_TicketDetailOutputSerializer(ticket).data)


class TicketMessageApi(APIView):
    class InputMessageSerializer(serializers.Serializer):
        message = serializers.CharField()

    @extend_schema(
        request=InputMessageSerializer,
        responses=_TicketMessageOutputSerializer,
        summary="Reply on a ticket (owner or admin)",
    )
    def post(self, request, ticket_id: int):
        ticket = get_ticket_for_user(user=request.user, ticket_id=ticket_id)
        serializer = self.InputMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = add_message(ticket=ticket, sender=request.user, message=serializer.validated_data["message"])
        return Response(_TicketMessageOutputSerializer(message).data)


class TicketCloseApi(APIView):
    @extend_schema(responses=_TicketOutputSerializer, summary="Close a ticket (owner or admin)")
    def post(self, request, ticket_id: int):
        ticket = get_ticket_for_user(user=request.user, ticket_id=ticket_id)
        ticket = close_ticket(ticket=ticket)
        return Response(_TicketOutputSerializer(ticket).data)


class AdminTicketListApi(APIView):
    permission_classes = [IsAdminUser]
    pagination_class = DefaultPagination

    @extend_schema(responses=_TicketOutputSerializer(many=True), summary="List all support tickets (admin)")
    def get(self, request):
        tickets = Ticket.objects.all()
        status_filter = request.query_params.get("status")
        if status_filter:
            tickets = tickets.filter(status=status_filter)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(tickets, request)
        return paginator.get_paginated_response(_TicketOutputSerializer(page, many=True).data)
