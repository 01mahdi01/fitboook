import base64
import datetime
import logging
import os
import uuid

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from config.errors import ApplicationError, NotFoundError, PermissionDeniedError
from courses import encription_methods
from courses.models import Course, CourseLink, CoursePdf, Enrollment, Video, VideoKeyIssuance
from courses.tasks import encrypt_and_upload_video
from storage import minio_apis
from users.models import BaseUser


def _default_expiry(course: Course) -> datetime.datetime | None:
    if course.access_duration_days is None:
        return None
    return timezone.now() + datetime.timedelta(days=course.access_duration_days)


logger = logging.getLogger(__name__)


def grant_enrollment(*, user: BaseUser, course: Course, expires_at=None) -> Enrollment:
    enrollment, created = Enrollment.objects.get_or_create(
        user=user, course=course, defaults={"expires_at": expires_at if expires_at is not None else _default_expiry(course)}
    )
    if not created and expires_at is not None:
        enrollment.expires_at = expires_at
        enrollment.save(update_fields=["expires_at"])
    return enrollment


def renew_enrollment(*, user: BaseUser, course: Course, expires_at=None) -> Enrollment:
    try:
        enrollment = Enrollment.objects.get(user=user, course=course)
    except Enrollment.DoesNotExist:
        raise NotFoundError("User is not enrolled in this course.")
    enrollment.expires_at = expires_at if expires_at is not None else _default_expiry(course)
    enrollment.save(update_fields=["expires_at"])
    return enrollment


def revoke_enrollment(*, user: BaseUser, course: Course) -> None:
    Enrollment.objects.filter(user=user, course=course).delete()


def get_user_enrollments(*, user: BaseUser) -> dict:
    enrollments = Enrollment.objects.filter(user=user).select_related("course")
    active, expired = [], []
    for enrollment in enrollments:
        (active if enrollment.is_active else expired).append(enrollment)
    return {"active": active, "expired": expired}


def create_course(**fields) -> Course:
    return Course.objects.create(**fields)


def upload_course_cover(*, course: Course, image_file: UploadedFile) -> Course:
    extension = os.path.splitext(image_file.name)[1]
    object_name = f"course_{course.id}/cover_{uuid.uuid4()}{extension}"
    url = minio_apis.upload_public_image(
        bucket=settings.MINIO_COURSE_COVER_BUCKET, object_name=object_name, file=image_file
    )
    course.cover_image_url = url
    course.save(update_fields=["cover_image_url"])
    return course


def update_course(*, course: Course, **fields) -> Course:
    for field, value in fields.items():
        setattr(course, field, value)
    course.save(update_fields=list(fields.keys()))
    return course


def delete_course(*, course: Course) -> None:
    for video in course.videos.exclude(object_name=""):
        minio_apis.delete_file(bucket=settings.MINIO_VIDEO_BUCKET, object_name=video.object_name)
    for pdf in course.pdfs.all():
        minio_apis.delete_file(bucket=settings.MINIO_COURSE_PDF_BUCKET, object_name=pdf.object_name)
    course.delete()


def delete_video(*, video: Video) -> None:
    if video.object_name:
        minio_apis.delete_file(bucket=settings.MINIO_VIDEO_BUCKET, object_name=video.object_name)
    video.delete()


def create_video_upload(
    *, course: Course, title: str, order: int, source_file: UploadedFile, description: str = ""
) -> Video:
    video = Video.objects.create(
        course=course, title=title, order=order, description=description, file_size_bytes=source_file.size
    )

    os.makedirs(settings.VIDEO_UPLOAD_TMP_DIR, exist_ok=True)
    tmp_path = os.path.join(settings.VIDEO_UPLOAD_TMP_DIR, f"{uuid.uuid4()}_{source_file.name}")
    with open(tmp_path, "wb") as tmp_file:
        for chunk in source_file.chunks():
            tmp_file.write(chunk)

    encrypt_and_upload_video.delay(video.id, tmp_path)
    video.refresh_from_db()
    return video


def ensure_course_access(*, user: BaseUser, course: Course) -> None:
    """Single gate for paid course content (videos, links, PDFs): staff, or an active enrollment."""
    if user.is_staff:
        return
    try:
        enrollment = Enrollment.objects.get(user=user, course=course)
    except Enrollment.DoesNotExist:
        raise PermissionDeniedError("You are not enrolled in this course.")
    if not enrollment.is_active:
        raise PermissionDeniedError("Your access to this course has expired.")


def get_course_materials(*, user: BaseUser, course: Course) -> dict:
    ensure_course_access(user=user, course=course)
    ttl = settings.MINIO_PRESIGNED_URL_TTL_SECONDS
    pdfs = list(course.pdfs.all())
    for pdf in pdfs:
        pdf.download_url = minio_apis.get_download_url(
            bucket=settings.MINIO_COURSE_PDF_BUCKET, object_name=pdf.object_name, ttl_seconds=ttl
        )
    return {"links": list(course.links.all()), "pdfs": pdfs, "expires_in": ttl}


def create_course_link(*, course: Course, title: str, url: str, order: int = 0) -> CourseLink:
    return CourseLink.objects.create(course=course, title=title, url=url, order=order)


def update_course_link(*, link: CourseLink, **fields) -> CourseLink:
    for field, value in fields.items():
        setattr(link, field, value)
    link.save(update_fields=list(fields.keys()))
    return link


def delete_course_link(*, link: CourseLink) -> None:
    link.delete()


def upload_course_pdf(*, course: Course, title: str, file: UploadedFile, order: int = 0) -> CoursePdf:
    # The PDF spec lets the "%PDF-" header sit anywhere in the first 1024 bytes, not only at offset 0.
    if b"%PDF-" not in file.read(1024):
        raise ApplicationError("File is not a PDF.")
    file.seek(0)
    object_name = f"course_{course.id}/{uuid.uuid4()}.pdf"
    bucket = settings.MINIO_COURSE_PDF_BUCKET
    minio_apis.upload_private_file(bucket=bucket, object_name=object_name, file=file, content_type="application/pdf")
    try:
        return CoursePdf.objects.create(
            course=course, title=title, order=order, object_name=object_name, file_size_bytes=file.size
        )
    except Exception:
        minio_apis.delete_file(bucket=bucket, object_name=object_name)  # don't orphan the uploaded file
        raise


def delete_course_pdf(*, pdf: CoursePdf) -> None:
    # Row first: a leftover file is harmless, a row pointing at a missing file breaks downloads.
    object_name = pdf.object_name
    pdf.delete()
    minio_apis.delete_file(bucket=settings.MINIO_COURSE_PDF_BUCKET, object_name=object_name)


def get_video_download_key(*, user: BaseUser, video_id: int, ip_address: str | None, device_id: str = "") -> dict:
    try:
        video = Video.objects.select_related("course").get(id=video_id)
    except Video.DoesNotExist:
        raise NotFoundError("Video not found.")

    if video.status != Video.ProcessingStatus.READY:
        raise NotFoundError("Video is not ready yet.")

    ensure_course_access(user=user, course=video.course)

    VideoKeyIssuance.objects.create(user=user, video=video, ip_address=ip_address, device_id=device_id)

    data_key = encription_methods.unwrap_data_key(video.wrapped_data_key, video.key_wrap_nonce)
    download_url = minio_apis.get_download_url(
        bucket=settings.MINIO_VIDEO_BUCKET,
        object_name=video.object_name,
        ttl_seconds=settings.MINIO_PRESIGNED_URL_TTL_SECONDS,
    )

    return {
        "download_url": download_url,
        "decryption_key": base64.b64encode(data_key).decode(),
        "nonce": base64.b64encode(bytes(video.content_nonce)).decode(),
        "expires_in": settings.MINIO_PRESIGNED_URL_TTL_SECONDS,
    }
