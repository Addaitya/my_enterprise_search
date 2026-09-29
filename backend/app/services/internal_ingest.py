"""Reserve a file_id and presigned PUT, then complete into files + OpenSearch.

Reserve does not insert ``files``. The pipeline writes bytes to MinIO.
Complete HEADs that object, upserts ``files``, and bulk-indexes the chunks
the pipeline already extracted. This path does not chunk, does not call
``detect_file_type``, and does not grant ``file_acl``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.file import FILE_INGESTION_TYPES, File
from app.models.ingest_job import IngestJob
from app.services.file_acl_admin import recompute_allowed_names
from app.services.ingest.detect import safe_filename
from app.services.minio_store import MinioStore
from app.services.opensearch_ingest import (
    build_chunk_document,
    bulk_index_chunks,
    delete_chunks_by_file_id,
)

logger = logging.getLogger(__name__)

_REUSABLE_JOB_STATUSES = frozenset({"reserved", "failed"})


class InternalIngestError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class ReserveResult:
    file_id: uuid.UUID
    object_store_path: str
    upload_url: str
    expires_at: datetime


@dataclass(frozen=True)
class CompleteResult:
    file_id: uuid.UUID
    status: str
    object_store_path: str
    file_type: str
    size_bytes: int
    ingestion_type: str
    chunk_count: int


def internal_object_path(ingestion_type: str, file_id: uuid.UUID, safe_name: str) -> str:
    """Object key for pipeline bytes. Never ``local/`` and never ``lake/``."""
    path = f"files/{ingestion_type}/{file_id}/{safe_name}"
    if path.startswith("lake/") or "/lake/" in f"/{path}":
        raise InternalIngestError(422, "lake/ prefix is not allowed")
    return path


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InternalIngestService:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        store: MinioStore | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.store = store or MinioStore(self.settings)

    def reserve(
        self,
        *,
        filename: str,
        size_bytes: int,
        ingestion_type: str,
        original_source: str,
        content_type: str | None = None,
    ) -> ReserveResult:
        """Allocate or reuse file_id, insert a reserved job, return a presigned PUT.

        ``content_type`` is accepted and ignored. ``files`` has no MIME column,
        and no ``files`` row is written here.
        """
        del content_type
        self._require_reserve_size(size_bytes)
        safe_name = self._require_filename(filename)
        source = self._require_source(original_source)
        self._require_ingestion_type(ingestion_type)

        existing = self._file_for_source(ingestion_type, source)
        if existing is not None:
            file_id = existing.id
        else:
            latest = self._latest_job_for_source(ingestion_type, source)
            if latest is not None and latest.status in _REUSABLE_JOB_STATUSES:
                file_id = latest.file_id
            else:
                file_id = uuid.uuid4()

        # A new job stores the path the PUT must use. A completed files row
        # keeps its object_store_path until complete succeeds.
        object_path = internal_object_path(ingestion_type, file_id, safe_name)
        now = _utcnow()
        expires_at = now + timedelta(seconds=self.settings.minio_presign_expiry_seconds)
        upload_url = self.store.presigned_put_url(
            object_path,
            expires_seconds=self.settings.minio_presign_expiry_seconds,
        )
        job = IngestJob(
            file_id=file_id,
            object_store_path=object_path,
            ingestion_type=ingestion_type,
            original_source=source,
            filename=safe_name,
            size_bytes=size_bytes,
            status="reserved",
            error=None,
            created_at=now,
            updated_at=now,
        )
        self.db.add(job)
        self.db.commit()
        return ReserveResult(
            file_id=file_id,
            object_store_path=object_path,
            upload_url=upload_url,
            expires_at=expires_at,
        )

    def complete(
        self,
        file_id: uuid.UUID,
        *,
        size_bytes: int,
        file_type: str,
        chunks: Sequence[tuple[int, str]],
    ) -> CompleteResult:
        """HEAD the reserved object, upsert files, bulk-index chunks."""
        checked_type = self._require_file_type(file_type)
        checked_chunks = self._require_chunks(chunks)
        job = self._latest_job_for_file(file_id)
        if job is None:
            raise InternalIngestError(404, "Ingest job not found")

        if job.status == "completed":
            if job.size_bytes == size_bytes:
                raise InternalIngestError(409, "already completed")
            raise InternalIngestError(
                409,
                "already completed with a different size; reserve again",
            )
        if job.status in {"failed", "expired"}:
            raise InternalIngestError(409, f"job is {job.status}; reserve again")

        try:
            actual = self.store.stat_object_size(job.object_store_path)
        except S3Error as exc:
            raise InternalIngestError(502, "object store unavailable") from exc
        if actual is None:
            raise InternalIngestError(409, "object not found")
        if actual != size_bytes or actual != job.size_bytes:
            raise InternalIngestError(422, "object size does not match size_bytes")

        job_id = job.id
        object_path = job.object_store_path
        ingestion_type = job.ingestion_type
        files_touched = False
        now = _utcnow()
        try:
            row = self._upsert_file(job, file_type=checked_type, size_bytes=size_bytes, now=now)
            self.db.flush()
            files_touched = True
            roles, groups = recompute_allowed_names(self.db, file_id)
            uploaded_at = row.uploaded_at.isoformat()
            updated_at = row.updated_at.isoformat()
            docs = [
                build_chunk_document(
                    file_id=file_id,
                    chunk_seq=seq,
                    content=content,
                    file_type=checked_type,
                    size_bytes=size_bytes,
                    object_store_path=object_path,
                    uploaded_at=uploaded_at,
                    updated_at=updated_at,
                    original_source=job.original_source,
                    ingestion_type=ingestion_type,
                    allowed_roles=roles,
                    allowed_groups=groups,
                )
                for seq, content in checked_chunks
            ]
            bulk_index_chunks(docs, settings=self.settings)
            job.status = "completed"
            job.completed_at = now
            job.updated_at = now
            job.error = None
            self.db.commit()
        except Exception as exc:
            logger.exception("internal ingest complete failed file_id=%s", file_id)
            if files_touched:
                try:
                    self._compensate(file_id=file_id, job_id=job_id, error=str(exc))
                except Exception:
                    logger.exception("internal ingest compensate failed file_id=%s", file_id)
            else:
                self.db.rollback()
            raise InternalIngestError(500, "ingest complete failed") from exc

        return CompleteResult(
            file_id=file_id,
            status="completed",
            object_store_path=object_path,
            file_type=checked_type,
            size_bytes=size_bytes,
            ingestion_type=ingestion_type,
            chunk_count=len(checked_chunks),
        )

    def _compensate(self, *, file_id: uuid.UUID, job_id: uuid.UUID, error: str) -> None:
        """Drop the files row and chunks. Leave the MinIO object for retry.

        A re-complete that updated an existing row deletes that row on failure,
        and ``file_acl`` cascades with it. The success path is what keeps grants.
        """
        self.db.rollback()
        try:
            delete_chunks_by_file_id(file_id, settings=self.settings)
        except Exception:
            logger.exception("internal ingest compensate: chunk delete failed file_id=%s", file_id)
        existing = self.db.get(File, file_id)
        if existing is not None:
            self.db.delete(existing)
            try:
                self.db.commit()
            except Exception:
                logger.exception("internal ingest compensate: files delete failed file_id=%s", file_id)
                self.db.rollback()
        job = self.db.get(IngestJob, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error = error[:4000]
        job.updated_at = _utcnow()
        job.completed_at = None
        self.db.commit()

    def _upsert_file(
        self,
        job: IngestJob,
        *,
        file_type: str,
        size_bytes: int,
        now: datetime,
    ) -> File:
        row = self.db.get(File, job.file_id)
        if row is None:
            row = File(
                id=job.file_id,
                object_store_path=job.object_store_path,
                file_type=file_type,
                size_bytes=size_bytes,
                ingestion_type=job.ingestion_type,
                original_source=job.original_source,
                uploaded_at=now,
                updated_at=now,
            )
            self.db.add(row)
            return row
        row.object_store_path = job.object_store_path
        row.file_type = file_type
        row.size_bytes = size_bytes
        row.ingestion_type = job.ingestion_type
        row.original_source = job.original_source
        row.updated_at = now
        return row

    def _require_reserve_size(self, size_bytes: int) -> None:
        limit = self.settings.pipeline_max_upload_bytes
        if size_bytes < 1 or size_bytes > limit:
            raise InternalIngestError(413, f"size_bytes must be between 1 and {limit}")

    def _require_filename(self, filename: str) -> str:
        try:
            return safe_filename(filename)
        except ValueError as exc:
            raise InternalIngestError(422, str(exc)) from exc

    def _require_source(self, original_source: str) -> str:
        source = original_source.strip()
        if not source:
            raise InternalIngestError(422, "original_source is required")
        return source

    def _require_ingestion_type(self, ingestion_type: str) -> None:
        if ingestion_type not in FILE_INGESTION_TYPES:
            raise InternalIngestError(422, "invalid ingestion_type")

    def _require_file_type(self, file_type: str) -> str:
        if not 1 <= len(file_type) <= 32 or any(char in file_type for char in "./\\"):
            raise InternalIngestError(422, "file_type must be 1-32 characters with no dot or slash")
        return file_type

    def _require_chunks(self, chunks: Sequence[tuple[int, str]]) -> list[tuple[int, str]]:
        if not chunks:
            raise InternalIngestError(422, "chunks must be a non-empty list")
        seen: set[int] = set()
        checked: list[tuple[int, str]] = []
        for seq, content in chunks:
            if seq < 0:
                raise InternalIngestError(422, "chunk seq must be >= 0")
            if seq in seen:
                raise InternalIngestError(422, "chunk seq must be unique")
            seen.add(seq)
            if content == "":
                raise InternalIngestError(422, "chunk content must be a non-empty string")
            checked.append((seq, content))
        checked.sort(key=lambda item: item[0])
        return checked

    def _file_for_source(self, ingestion_type: str, original_source: str) -> File | None:
        return self.db.scalar(
            select(File).where(
                File.ingestion_type == ingestion_type,
                File.original_source == original_source,
            )
        )

    def _latest_job_for_source(self, ingestion_type: str, original_source: str) -> IngestJob | None:
        return self.db.scalar(
            select(IngestJob)
            .where(
                IngestJob.ingestion_type == ingestion_type,
                IngestJob.original_source == original_source,
            )
            .order_by(IngestJob.created_at.desc(), IngestJob.id.desc())
            .limit(1)
        )

    def _latest_job_for_file(self, file_id: uuid.UUID) -> IngestJob | None:
        return self.db.scalar(
            select(IngestJob)
            .where(IngestJob.file_id == file_id)
            .order_by(IngestJob.created_at.desc(), IngestJob.id.desc())
            .limit(1)
        )
