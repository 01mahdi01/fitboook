from django.db.models import Count, Sum

from purchases.models import Purchase


def get_financial_report(*, date_from=None, date_to=None) -> dict:
    purchases = Purchase.objects.filter(status=Purchase.Status.PAID)
    if date_from:
        purchases = purchases.filter(paid_at__gte=date_from)
    if date_to:
        purchases = purchases.filter(paid_at__lte=date_to)

    totals = purchases.aggregate(total_revenue=Sum("amount"), total_sales=Count("id"))
    by_course = (
        purchases.values("course_id", "course__title")
        .annotate(revenue=Sum("amount"), sales=Count("id"))
        .order_by("-revenue")
    )
    by_course = [
        {"course_id": row["course_id"], "course_title": row["course__title"], "revenue": row["revenue"], "sales": row["sales"]}
        for row in by_course
    ]

    return {
        "total_revenue": totals["total_revenue"] or 0,
        "total_sales": totals["total_sales"] or 0,
        "by_course": list(by_course),
    }
