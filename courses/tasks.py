import logging
import os

from celery import shared_task
from django.conf import settings

from courses import encription_methods
from courses.models import Video
from storage import minio_apis

logger = logging.getLogger(__name__)


@shared_task
def encrypt_and_upload_video(video_id: int, tmp_file_path: str) -> None:
    video = Video.objects.get(id=video_id)
    video.status = Video.ProcessingStatus.PROCESSING
    video.save(update_fields=["status"])

    encrypted_path = f"{tmp_file_path}.enc"
    data_key = encription_methods.generate_data_key()

    try:
        nonce = encription_methods.encrypt_file(
            source_path=tmp_file_path, dest_path=encrypted_path, data_key=data_key
        )
        object_name = f"course_{video.course_id}/video_{video.id}.enc"
        minio_apis.upload_file(
            bucket=settings.MINIO_VIDEO_BUCKET, object_name=object_name, file_path=encrypted_path
        )
        wrapped_key, key_wrap_nonce = encription_methods.wrap_data_key(data_key)

        video.object_name = object_name
        video.wrapped_data_key = wrapped_key
        video.key_wrap_nonce = key_wrap_nonce
        video.content_nonce = nonce
        video.status = Video.ProcessingStatus.READY
        video.save(
            update_fields=["object_name", "wrapped_data_key", "key_wrap_nonce", "content_nonce", "status"]
        )
    except Exception:
        logger.exception("Failed to encrypt/upload video %s", video_id)
        video.status = Video.ProcessingStatus.FAILED
        video.save(update_fields=["status"])
        raise
    finally:
        for path in (tmp_file_path, encrypted_path):
            if os.path.exists(path):
                os.remove(path)
