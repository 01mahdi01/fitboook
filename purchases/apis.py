import logging

from django.conf import settings
from django.shortcuts import get_object_or_404, render
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApplicationError
from config.pagination import DefaultPagination
from courses.models import Course
from purchases.models import Purchase
from purchases.services import get_financial_report
from purchases.zarinpal_services import confirm_course_purchase, start_course_purchase
from users.models import BaseUser


class PurchaseCourseApi(APIView):
    class InputPurchaseSerializer(serializers.Serializer):
        course_id = serializers.IntegerField()

    class OutputPurchaseSerializer(serializers.Serializer):
        payment_url = serializers.CharField()
        purchase_id = serializers.IntegerField()

    @extend_schema(
        request=InputPurchaseSerializer,
        responses=OutputPurchaseSerializer,
        summary="Start a ZarinPal payment for a course",
    )
    def post(self, request):
        serializer = self.InputPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        course = get_object_or_404(Course, id=serializer.validated_data["course_id"])
        result = start_course_purchase(
            user=request.user, course=course, callback_base_url=settings.PUBLIC_BASE_URL
        )
        return Response(self.OutputPurchaseSerializer(result).data)


@permission_classes([AllowAny])
class PurchaseCallbackApi(APIView):
    @extend_schema(
        summary="ZarinPal payment callback",
        description=(
            "ZarinPal redirects the user's browser here after payment. `purchase_id` is the id we put on the "
            "callback URL when starting the payment (see POST /api/purchases/); `Authority` and `Status` are "
            "added by ZarinPal itself. `Status=OK` means the user completed payment on ZarinPal's side, but the "
            "purchase is only confirmed as PAID after `confirm_course_purchase` verifies it server-side below. "
            "Renders a Persian-language HTML page (not JSON) with a button deep-linking back into the app "
            "(fitboook://payment/callback), since this URL is opened directly in the user's browser by ZarinPal."
        ),
        parameters=[
            OpenApiParameter(
                name="purchase_id", type=int, location=OpenApiParameter.QUERY, required=True,
                description="Our internal Purchase id, echoed back from the callback_url we gave ZarinPal.",
            ),
            OpenApiParameter(
                name="Authority", type=str, location=OpenApiParameter.QUERY, required=True,
                description="ZarinPal's payment authority token for this transaction.",
            ),
            OpenApiParameter(
                name="Status", type=str, location=OpenApiParameter.QUERY, required=False,
                description="'OK' if the user completed payment, 'NOK' if they cancelled. Informational only; "
                "the server always re-verifies with ZarinPal regardless of this value.",
            ),
        ],
    )
    def get(self, request):
        purchase_id = request.query_params.get("purchase_id")
        authority = request.query_params.get("Authority")
        try:
            confirm_course_purchase(purchase_id=purchase_id, authority=authority)
        except ApplicationError as e:
            return render(request, "purchases/callback.html", {"success": False, "message": e.message})
        except Purchase.DoesNotExist:
            return render(
                request, "purchases/callback.html", {"success": False, "message": "تراکنش یافت نشد."}
            )
        except Exception:
            # Anything else here is a real bug (e.g. a bad type reaching the ZarinPal call), not a normal
            # "payment failed" outcome — log it loudly so it doesn't silently masquerade as "not found".
            logging.getLogger(__name__).exception(
                "Unexpected error confirming purchase_id=%s authority=%s", purchase_id, authority
            )
            return render(
                request, "purchases/callback.html", {"success": False, "message": "خطای غیرمنتظره‌ای رخ داد."}
            )
        return render(request, "purchases/callback.html", {"success": True})


class MyPurchasesApi(APIView):
    class OutputMyPurchaseSerializer(serializers.ModelSerializer):
        course_id = serializers.IntegerField()
        course_title = serializers.CharField(source="course.title")

        class Meta:
            model = Purchase
            fields = ["id", "course_id", "course_title", "amount", "status", "paid_at", "created_at"]

    @extend_schema(responses=OutputMyPurchaseSerializer(many=True), summary="List the current user's purchases")
    def get(self, request):
        purchases = Purchase.objects.filter(user=request.user).select_related("course").order_by("-created_at")
        return Response(self.OutputMyPurchaseSerializer(purchases, many=True).data)


class _CourseRevenueSerializer(serializers.Serializer):
    course_id = serializers.IntegerField()
    course_title = serializers.CharField()
    revenue = serializers.IntegerField()
    sales = serializers.IntegerField()


class FinancialReportApi(APIView):
    permission_classes = [IsAdminUser]

    OutputCourseRevenueSerializer = _CourseRevenueSerializer

    class OutputFinancialReportSerializer(serializers.Serializer):
        total_revenue = serializers.IntegerField()
        total_sales = serializers.IntegerField()
        by_course = _CourseRevenueSerializer(many=True)

    @extend_schema(responses=OutputFinancialReportSerializer, summary="Admin financial report")
    def get(self, request):
        report = get_financial_report(
            date_from=request.query_params.get("date_from"),
            date_to=request.query_params.get("date_to"),
        )
        return Response(self.OutputFinancialReportSerializer(report).data)


class _AdminPurchaseOutputSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField()
    user_email = serializers.EmailField(source="user.email")
    user_name = serializers.CharField(source="user.full_name")
    user_phone = serializers.CharField(source="user.phone")
    course_id = serializers.IntegerField()
    course_title = serializers.CharField(source="course.title")

    class Meta:
        model = Purchase
        fields = [
            "id",
            "user_id",
            "user_email",
            "user_name",
            "user_phone",
            "course_id",
            "course_title",
            "amount",
            "status",
            "ref_id",
            "paid_at",
            "created_at",
        ]


class AdminPurchaseListApi(APIView):
    permission_classes = [IsAdminUser]
    pagination_class = DefaultPagination

    OutputPurchaseListSerializer = _AdminPurchaseOutputSerializer

    @extend_schema(responses=_AdminPurchaseOutputSerializer(many=True), summary="List all purchases (admin)")
    def get(self, request):
        purchases = Purchase.objects.select_related("user", "course").order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            purchases = purchases.filter(status=status_filter)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(purchases, request)
        return paginator.get_paginated_response(_AdminPurchaseOutputSerializer(page, many=True).data)


class AdminUserPurchasesApi(APIView):
    """List a specific user's purchase/transaction history, for the admin user-detail page."""

    permission_classes = [IsAdminUser]
    pagination_class = DefaultPagination

    @extend_schema(
        responses=_AdminPurchaseOutputSerializer(many=True), summary="List a user's purchases/transactions (admin)"
    )
    def get(self, request, user_id: int):
        get_object_or_404(BaseUser, id=user_id)
        purchases = (
            Purchase.objects.filter(user_id=user_id).select_related("user", "course").order_by("-created_at")
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(purchases, request)
        return paginator.get_paginated_response(_AdminPurchaseOutputSerializer(page, many=True).data)
