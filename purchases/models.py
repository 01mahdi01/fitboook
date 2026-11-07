from django.conf import settings
from django.db import models

from courses.models import Course


class Purchase(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        PAID = "paid"
        FAILED = "failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="purchases", on_delete=models.CASCADE)
    course = models.ForeignKey(Course, related_name="purchases", on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    authority = models.CharField(max_length=100, blank=True)
    ref_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user_id} - {self.course_id} - {self.status}"
