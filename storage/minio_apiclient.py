import json
from datetime import timedelta

from django.conf import settings
from minio import Minio


MINIO_REGION = "us-east-1"  # MinIO's default single-region setup — see comment below for why this is pinned.


def get_client() -> Minio:
    """Client used for actual bucket operations (upload/delete/bucket-policy) — talks to MinIO over the internal network."""
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
        region=MINIO_REGION,
    )


def get_public_client() -> Minio:
    """Client used only to build URLs handed to browsers/apps (presigned GETs, public cover URLs).

    Presigning doesn't require connectivity to the endpoint — it just signs a URL — so this can point at a
    publicly reachable host/port even though MINIO_ENDPOINT (used by get_client) is an internal docker hostname.

    region is pinned explicitly: without it, minio-py calls the bucket's GetBucketLocation API on first use to
    auto-detect the region — a real network call made through THIS client, i.e. against the public domain. That
    made every presigned-URL request depend on this container successfully resolving the public domain's DNS
    over the internet, which is unreliable — intermittent DNS failures here surfaced as random 500s from
    VideoKeyApi. Pinning the region (MinIO's fixed single-region setup, never changes) skips that lookup entirely.
    """
    return Minio(
        settings.MINIO_PUBLIC_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_PUBLIC_SECURE,
        region=MINIO_REGION,
    )


def ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def ensure_public_bucket(client: Minio, bucket: str) -> None:
    ensure_bucket(client, bucket)
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            }
        ],
    }
    client.set_bucket_policy(bucket, json.dumps(policy))


def put_object(client: Minio, bucket: str, object_name: str, file_path: str) -> None:
    client.fput_object(bucket, object_name, file_path)


def put_object_stream(client: Minio, bucket: str, object_name: str, data, length: int, content_type: str) -> None:
    client.put_object(bucket, object_name, data, length, content_type=content_type)


def presigned_get_url(bucket: str, object_name: str, ttl_seconds: int) -> str:
    client = get_public_client()
    return client.presigned_get_object(bucket, object_name, expires=timedelta(seconds=ttl_seconds))


def remove_object(client: Minio, bucket: str, object_name: str) -> None:
    client.remove_object(bucket, object_name)
