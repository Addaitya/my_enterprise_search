"""MinIO object store — single full-object puts only (no multipart / no ranged writes).

Drive-style resumable ranges are assembled in local staging first; MinIO receives
one complete object at ``local/{file_id}/{safe_name}`` on successful complete.
"""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from typing import Any

from minio import Minio
from minio.error import S3Error

from app.core.config import Settings, get_settings


def minio_client(settings: Settings | None = None) -> Minio:
    settings = settings or get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_secure,
    )


def final_object_path(file_id: str, safe_filename: str) -> str:
    return f"local/{file_id}/{safe_filename}"


class MinioStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = minio_client(self.settings)
        self.bucket = self.settings.minio_bucket

    def put_object(self, object_store_path: str, data: bytes, *, content_type: str | None = None) -> None:
        """Upload the full file as one object. No multipart, no partial ranges."""
        self.client.put_object(
            self.bucket,
            object_store_path,
            BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )

    def delete_object(self, object_store_path: str) -> None:
        try:
            self.client.remove_object(self.bucket, object_store_path)
        except S3Error:
            pass

    def object_exists(self, object_store_path: str) -> bool:
        try:
            self.client.stat_object(self.bucket, object_store_path)
            return True
        except S3Error:
            return False

    def get_object_bytes(self, object_store_path: str) -> bytes:
        """Read full object into memory (small files / proofs)."""
        response: Any = None
        try:
            response = self.client.get_object(self.bucket, object_store_path)
            return response.read()
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def iter_object(
        self,
        object_store_path: str,
        *,
        chunk_size: int = 1024 * 64,
    ) -> Iterator[bytes]:
        """Stream object bytes. Closes the MinIO response when the iterator ends."""
        response = self.client.get_object(self.bucket, object_store_path)
        try:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            response.close()
            response.release_conn()
