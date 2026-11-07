import logging

from django.urls import reverse
from django.utils import timezone

from config.errors import ApplicationError
from courses.models import Course
from courses.services import grant_enrollment
from purchases import zarinpal_apis
from purchases.zarinpal_apiclient import STARTPAY_URL
from purchases.models import Purchase
from users.models import BaseUser

logger = logging.getLogger(__name__)

# Prices/amounts are stored and displayed in Toman everywhere in this app, but ZarinPal's API always expects
# Rial — convert only at the ZarinPal call boundary, never touch the stored/displayed amount itself.
TOMAN_TO_RIAL = 10


def start_course_purchase(*, user: BaseUser, course: Course, callback_base_url: str) -> dict:
    amount = int(course.price)
    purchase = Purchase.objects.create(user=user, course=course, amount=amount)

    callback_url = f"{callback_base_url}{reverse('purchase-callback')}?purchase_id={purchase.id}"
    try:
        result = zarinpal_apis.create_payment_request(
            amount=amount * TOMAN_TO_RIAL, description=f"Purchase: {course.title}", callback_url=callback_url
        )
    except ApplicationError:
        purchase.status = Purchase.Status.FAILED
        purchase.save(update_fields=["status"])
        raise

    data = result.get("data") or {}
    authority = data.get("authority")
    if not authority:
        purchase.status = Purchase.Status.FAILED
        purchase.save(update_fields=["status"])
        raise ApplicationError("Could not start payment with ZarinPal.")

    purchase.authority = authority
    purchase.save(update_fields=["authority"])

    return {"payment_url": f"{STARTPAY_URL}/{authority}", "purchase_id": purchase.id}


def confirm_course_purchase(*, purchase_id: int, authority: str) -> Purchase:
    purchase = Purchase.objects.select_related("course", "user").get(id=purchase_id)

    if purchase.status == Purchase.Status.PAID:
        return purchase

    try:
        result = zarinpal_apis.confirm_payment(amount=int(purchase.amount) * TOMAN_TO_RIAL, authority=authority)
    except ApplicationError:
        purchase.status = Purchase.Status.FAILED
        purchase.save(update_fields=["status"])
        raise
    data = result.get("data") or {}

    if data.get("code") not in (100, 101):
        purchase.status = Purchase.Status.FAILED
        purchase.save(update_fields=["status"])
        raise ApplicationError("Payment verification failed.")

    purchase.status = Purchase.Status.PAID
    purchase.ref_id = str(data.get("ref_id", ""))
    purchase.paid_at = timezone.now()
    purchase.save(update_fields=["status", "ref_id", "paid_at"])

    grant_enrollment(user=purchase.user, course=purchase.course)

    return purchase
