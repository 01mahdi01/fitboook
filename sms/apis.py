from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from sms.services import send_sms_to_users


class AdminSendSmsApi(APIView):
    """Send one message to specific users (`user_ids`, one or many) or to every active user (`send_to_all`)."""

    permission_classes = [IsAdminUser]

    class InputSendSmsSerializer(serializers.Serializer):
        message = serializers.CharField()
        user_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=False)
        send_to_all = serializers.BooleanField(default=False)

        def validate(self, data):
            if data["send_to_all"] == ("user_ids" in data):
                raise serializers.ValidationError("Provide either user_ids or send_to_all=true, not both.")
            return data

    class OutputSendSmsSerializer(serializers.Serializer):
        recipients = serializers.IntegerField()

    @extend_schema(
        tags=["sms"],
        request=InputSendSmsSerializer,
        responses={200: OutputSendSmsSerializer},
        summary="Send an SMS to selected users or all users (admin)",
        description="Sent immediately with up to 3 attempts per batch. On failure returns 502 with `detail` "
        "explaining why (e.g. no credit) and, for large sends, how many recipients were already delivered.",
    )
    def post(self, request):
        serializer = self.InputSendSmsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        recipients = send_sms_to_users(
            message=serializer.validated_data["message"],
            user_ids=serializer.validated_data.get("user_ids"),
        )
        return Response(self.OutputSendSmsSerializer({"recipients": recipients}).data)
