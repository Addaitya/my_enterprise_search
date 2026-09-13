"""Shared bytes → MinIO + ``files`` + OpenSearch chunks (C6).

Used by HTTP ``UploadService.complete`` and the folder CLI so chunking,
object paths, ``files`` inserts, OS doc shape, and compensation stay one path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.file import File
from app.services.ingest import IngestParseError, build_content_chunks
from app.services.ingest.detect import detect_file_type, safe_filename
from app.services.minio_store import MinioStore, final_object_path
from app.services.opensearch_ingest import (
    build_chunk_document,
    bulk_index_chunks,
    delete_chunks_by_file_id,
)


@dataclass(frozen=True)
class LocalIngestResult:
    file_id: uuid.UUID
    file_type: str
    size_bytes: int
    object_store_path: str
    chunk_count: int
    uploaded_at: datetime


def compensate_local_ingest(
    db: Session,
    *,
    file_id: uuid.UUID | None,
    object_store_path: str | None,
    indexed: bool,
    minio_written: bool,
    store: MinioStore,
    settings: Settings,
) -> None:
    """C6: drop orphan ``files`` / OS chunks / MinIO object. Best-effort deletes."""
    db.rollback()
    if indexed and file_id is not None:
        try:
            delete_chunks_by_file_id(file_id, settings=settings)
        except Exception:  # noqa: BLE001
            pass
    if file_id is not None:
        existing = db.get(File, file_id)
        if existing is not None:
            db.delete(existing)
            db.commit()
    if minio_written and object_store_path:
        try:
            store.delete_object(object_store_path)
        except Exception:  # noqa: BLE001
            pass


def ingest_local_bytes(
    db: Session,
    *,
    data: bytes,
    filename: str,
    original_source: str | None = None,
    settings: Settings | None = None,
    store: MinioStore | None = None,
) -> LocalIngestResult:
    """Parse → chunk → MinIO → files row → OS bulk. C6 on failure.

    ``filename`` is used only for safe_filename + file_type detection.
    Caller must already have enforced size cap if desired.
    """
    settings = settings or get_settings()
    store = store or MinioStore(settings)

    try:
        name = safe_filename(filename)
        file_type = detect_file_type(name)
    except ValueError as exc:
        raise IngestParseError(str(exc)) from exc

    minio_written = False
    indexed = False
    file_id: uuid.UUID | None = None
    object_path: str | None = None

    try:
        chunks = build_content_chunks(
            file_type=file_type,
            data=data,
            chunk_tokens=settings.ingest_chunk_tokens,
            overlap_tokens=settings.ingest_chunk_overlap_tokens,
        )

        file_id = uuid.uuid4()
        object_path = final_object_path(str(file_id), name)

        store.put_object(object_path, data)
        minio_written = True

        now = datetime.now(timezone.utc)
        file_row = File(
            id=file_id,
            object_store_path=object_path,
            file_type=file_type,
            size_bytes=len(data),
            ingestion_type="local",
            original_source=original_source,
            uploaded_at=now,
            updated_at=now,
        )
        db.add(file_row)
        db.flush()

        iso = now.isoformat()
        docs = [
            build_chunk_document(
                file_id=file_id,
                chunk_seq=seq,
                content=content,
                file_type=file_type,
                size_bytes=len(data),
                object_store_path=object_path,
                uploaded_at=iso,
                updated_at=iso,
                original_source=original_source,
            )
            for seq, content in enumerate(chunks)
        ]
        bulk_index_chunks(docs, settings=settings)
        indexed = True

        db.commit()
        db.refresh(file_row)

        return LocalIngestResult(
            file_id=file_row.id,
            file_type=file_row.file_type,
            size_bytes=file_row.size_bytes,
            object_store_path=file_row.object_store_path,
            chunk_count=len(chunks),
            uploaded_at=file_row.uploaded_at,
        )
    except Exception:
        compensate_local_ingest(
            db,
            file_id=file_id,
            object_store_path=object_path,
            indexed=indexed,
            minio_written=minio_written,
            store=store,
            settings=settings,
        )
        raise
