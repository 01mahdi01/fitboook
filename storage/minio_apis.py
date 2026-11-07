from django.conf import settings

from storage import minio_apiclient


def upload_file(*, bucket: str, object_name: str, file_path: str) -> None:
    client = minio_apiclient.get_client()
    minio_apiclient.ensure_bucket(client, bucket)
    minio_apiclient.put_object(client, bucket, object_name, file_path)


def upload_public_image(*, bucket: str, object_name: str, file) -> str:
    """Upload an image to a public-read bucket and return its publicly reachable direct URL."""
    client = minio_apiclient.get_client()
    minio_apiclient.ensure_public_bucket(client, bucket)
    minio_apiclient.put_object_stream(
        client, bucket, object_name, file, file.size, file.content_type or "application/octet-stream"
    )
    scheme = "https" if settings.MINIO_PUBLIC_SECURE else "http"
    return f"{scheme}://{settings.MINIO_PUBLIC_ENDPOINT}/{bucket}/{object_name}"


def get_download_url(*, bucket: str, object_name: str, ttl_seconds: int) -> str:
    return minio_apiclient.presigned_get_url(bucket, object_name, ttl_seconds)


def delete_file(*, bucket: str, object_name: str) -> None:
    client = minio_apiclient.get_client()
    minio_apiclient.remove_object(client, bucket, object_name)
