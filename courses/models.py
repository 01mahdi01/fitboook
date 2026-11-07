from django.conf import settings
from django.db import models
from django.utils import timezone


class Course(models.Model):
    class Level(models.TextChoices):
        BEGINNER = "beginner"
        INTERMEDIATE = "intermediate"
        ADVANCED = "advanced"

    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    short_description = models.CharField(max_length=500, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=0)
    is_published = models.BooleanField(default=False)
    instructor_name = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=100, blank=True)
    level = models.CharField(max_length=20, choices=Level.choices, blank=True)
    cover_image_url = models.URLField(blank=True)
    benefits = models.TextField(blank=True, help_text="One benefit per line.")
    access_duration_days = models.PositiveIntegerField(
        null=True, blank=True, help_text="Enrollment length granted on purchase. Blank = lifetime access."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Video(models.Model):
    class ProcessingStatus(models.TextChoices):
        PENDING = "pending"
        PROCESSING = "processing"
        READY = "ready"
        FAILED = "failed"

    course = models.ForeignKey(Course, related_name="videos", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    file_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    object_name = models.CharField(max_length=255, blank=True)
    wrapped_data_key = models.BinaryField(null=True, blank=True)
    key_wrap_nonce = models.BinaryField(null=True, blank=True)
    content_nonce = models.BinaryField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=ProcessingStatus.choices, default=ProcessingStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.course.title} - {self.title}"



class CourseLink(models.Model):
    """External link attached to a course (e.g. a Telegram group, a form); shown only to enrolled users."""

    course = models.ForeignKey(Course, related_name="links", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    url = models.URLField(max_length=1000)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.course.title} - {self.title}"


class CoursePdf(models.Model):
    """PDF stored in the private MinIO bucket (settings.MINIO_COURSE_PDF_BUCKET) at `object_name`;
    enrolled users get short-lived presigned URLs, never a permanent link."""

    course = models.ForeignKey(Course, related_name="pdfs", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)
    object_name = models.CharField(max_length=255)
    file_size_bytes = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.course.title} - {self.title}"

class Enrollment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="enrollments", on_delete=models.CASCADE)
    course = models.ForeignKey(Course, related_name="enrollments", on_delete=models.CASCADE)
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Blank = lifetime access.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["user", "course"]

    @property
    def is_active(self) -> bool:
        return self.expires_at is None or self.expires_at > timezone.now()

    def __str__(self):
        return f"{self.user_id} -> {self.course_id}"


class VideoKeyIssuance(models.Model):
    """Audit trail: every time a decryption key is handed to a client."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="video_key_issuances", on_delete=models.CASCADE)
    video = models.ForeignKey(Video, related_name="key_issuances", on_delete=models.CASCADE)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    device_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
