from __future__ import annotations

from minio import Minio

from app.core.config import get_settings


def ensure_bucket() -> None:
    settings = get_settings()
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_secure,
    )
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
        print(f"[ok] created minio bucket {settings.minio_bucket}")
    else:
        print(f"[ok] minio bucket {settings.minio_bucket} exists")


def configure() -> None:
    ensure_bucket()
