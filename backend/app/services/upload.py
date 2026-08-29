"""Resumable upload session service + process orchestrator (C6/C8)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.file import File
from app.models.upload_session import UploadSession
from app.services.ingest import IngestParseError, build_content_chunks
from app.services.ingest.detect import detect_file_type, safe_filename
from app.services.local_staging import LocalStaging
from app.services.minio_store import MinioStore, final_object_path
from app.services.opensearch_ingest import (
    build_chunk_document,
    bulk_index_chunks,
    delete_chunks_by_file_id,
)

_CONTENT_RANGE_PUT_RE = re.compile(
    r"^bytes\s+(\d+)-(\d+)/(\d+)$",
    re.IGNORECASE,
)
_CONTENT_RANGE_STATUS_RE = re.compile(
    r"^bytes\s+\*/(\d+)$",
    re.IGNORECASE,
)


class UploadServiceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def parse_content_range(header: str | None) -> tuple[int, int, int] | tuple[None, None, int]:
    """Parse Drive-style Content-Range.

    Returns ``(start, end, total)`` for a byte PUT, or ``(None, None, total)``
    for a status probe (``bytes */total``).
    """
    if not header:
        raise UploadServiceError(400, "Content-Range header required")
    text = header.strip()
    status = _CONTENT_RANGE_STATUS_RE.match(text)
    if status:
        return None, None, int(status.group(1))
    match = _CONTENT_RANGE_PUT_RE.match(text)
    if not match:
        raise UploadServiceError(400, "invalid Content-Range")
    start = int(match.group(1))
    end = int(match.group(2))
    total = int(match.group(3))
    if end < start:
        raise UploadServiceError(400, "Content-Range end < start")
    return start, end, total


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UploadService:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        store: MinioStore | None = None,
        staging: LocalStaging | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.store = store or MinioStore(self.settings)
        self.staging = staging or LocalStaging(self.settings)

    def initiate(
        self,
        *,
        user_sub: str,
        filename: str,
        size_bytes: int,
        content_type: str | None = None,
    ) -> UploadSession:
        del content_type  # advisory only
        if size_bytes > self.settings.ingest_max_upload_bytes:
            raise UploadServiceError(413, "file exceeds ingest_max_upload_bytes")
        try:
            name = safe_filename(filename)
            file_type = detect_file_type(name)
        except ValueError as exc:
            raise UploadServiceError(415, str(exc)) from exc

        upload_id = uuid.uuid4()
        staging_path = self.staging.ensure(str(upload_id))
        expires_at = _utcnow() + timedelta(hours=self.settings.ingest_upload_session_ttl_hours)
        session = UploadSession(
            id=upload_id,
            user_id=user_sub,
            safe_filename=name,
            file_type=file_type,
            size_bytes=size_bytes,
            bytes_received=0,
            status="initiated",
            staging_path=staging_path,
            expires_at=expires_at,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_owned(self, upload_id: uuid.UUID, user_sub: str) -> UploadSession:
        session = self.db.get(UploadSession, upload_id)
        if session is None:
            raise UploadServiceError(404, "upload session not found")
        if session.user_id != user_sub:
            raise UploadServiceError(403, "Forbidden")
        self._expire_if_needed(session)
        return session

    def put_range(
        self,
        *,
        upload_id: uuid.UUID,
        user_sub: str,
        content_range: str | None,
        body: bytes,
    ) -> UploadSession:
        session = self.get_owned(upload_id, user_sub)
        if session.status in {"completed", "processing", "cancelled"}:
            raise UploadServiceError(409, f"upload session is {session.status}")
        if session.status == "failed":
            raise UploadServiceError(409, "upload session failed; start a new upload")
        if session.status == "expired":
            raise UploadServiceError(410, "upload session expired")

        start, end, total = parse_content_range(content_range)
        if total != session.size_bytes:
            raise UploadServiceError(400, "Content-Range total does not match declared size_bytes")

        # Status probe: Content-Range: bytes */total (empty body).
        if start is None:
            return session

        assert end is not None
        if end - start + 1 != len(body):
            raise UploadServiceError(400, "body length does not match Content-Range span")
        if start != session.bytes_received:
            raise UploadServiceError(
                400,
                f"non-sequential range: expected start={session.bytes_received}, got {start}",
            )
        if end >= session.size_bytes:
            raise UploadServiceError(400, "range exceeds declared size_bytes")

        try:
            written = self.staging.put_range(str(session.id), start, body)
        except ValueError as exc:
            raise UploadServiceError(400, str(exc)) from exc

        session.bytes_received = written
        session.status = "uploading"
        session.updated_at = _utcnow()
        self.db.commit()
        self.db.refresh(session)
        return session

    def complete(self, *, upload_id: uuid.UUID, user_sub: str) -> tuple[UploadSession, File]:
        session = self.get_owned(upload_id, user_sub)
        if session.status == "completed" and session.file_id is not None:
            file_row = self.db.get(File, session.file_id)
            if file_row is None:
                raise UploadServiceError(500, "completed session missing files row")
            raise UploadServiceError(409, "upload already completed")
        if session.status == "processing":
            raise UploadServiceError(409, "upload is already processing")
        if session.status in {"cancelled", "expired"}:
            raise UploadServiceError(409, f"upload session is {session.status}")
        if session.status == "failed":
            raise UploadServiceError(409, session.error_message or "upload failed")
        if session.bytes_received != session.size_bytes:
            raise UploadServiceError(
                400,
                f"incomplete upload: {session.bytes_received}/{session.size_bytes} bytes",
            )

        session.status = "processing"
        session.error_message = None
        session.updated_at = _utcnow()
        self.db.commit()

        file_id = uuid.uuid4()
        object_path = final_object_path(str(file_id), session.safe_filename)
        file_row: File | None = None
        indexed = False
        minio_written = False

        try:
            data = self.staging.read_bytes(str(session.id))
            if len(data) != session.size_bytes:
                raise IngestParseError(
                    f"staging size mismatch: got {len(data)}, expected {session.size_bytes}"
                )

            chunks = build_content_chunks(
                file_type=session.file_type,
                data=data,
                chunk_tokens=self.settings.ingest_chunk_tokens,
                overlap_tokens=self.settings.ingest_chunk_overlap_tokens,
            )

            # Single full-object put — no MinIO multipart / ranged upload.
            self.store.put_object(object_path, data)
            minio_written = True

            now = _utcnow()
            file_row = File(
                id=file_id,
                object_store_path=object_path,
                file_type=session.file_type,
                size_bytes=session.size_bytes,
                ingestion_type="local",
                original_source=None,
                uploaded_at=now,
                updated_at=now,
            )
            self.db.add(file_row)
            self.db.flush()

            iso = now.isoformat()
            docs = [
                build_chunk_document(
                    file_id=file_id,
                    chunk_seq=seq,
                    content=content,
                    file_type=session.file_type,
                    size_bytes=session.size_bytes,
                    object_store_path=object_path,
                    uploaded_at=iso,
                    updated_at=iso,
                )
                for seq, content in enumerate(chunks)
            ]
            bulk_index_chunks(docs, settings=self.settings)
            indexed = True

            session.file_id = file_id
            session.chunk_count = len(chunks)
            session.status = "completed"
            session.updated_at = _utcnow()
            self.db.commit()
            self.db.refresh(session)
            self.db.refresh(file_row)

            try:
                self.staging.delete(str(session.id))
            except Exception:  # noqa: BLE001 — local staging GC best-effort after success
                pass

            return session, file_row

        except IngestParseError as exc:
            self._compensate(
                session, file_id, object_path, file_row, indexed, minio_written, str(exc)
            )
            raise UploadServiceError(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            self._compensate(
                session, file_id, object_path, file_row, indexed, minio_written, str(exc)
            )
            raise UploadServiceError(502, f"ingest failed: {exc}") from exc

    def cancel(self, *, upload_id: uuid.UUID, user_sub: str) -> UploadSession:
        session = self.get_owned(upload_id, user_sub)
        if session.status == "completed":
            raise UploadServiceError(409, "cannot cancel completed upload")
        if session.status == "processing":
            raise UploadServiceError(409, "cannot cancel while processing")
        try:
            self.staging.delete(str(session.id))
        except Exception:  # noqa: BLE001
            pass
        session.status = "cancelled"
        session.updated_at = _utcnow()
        self.db.commit()
        self.db.refresh(session)
        return session

    def _compensate(
        self,
        session: UploadSession,
        file_id: uuid.UUID,
        object_path: str,
        file_row: File | None,
        indexed: bool,
        minio_written: bool,
        error: str,
    ) -> None:
        """C6: no orphan files/chunks/MinIO object; local staging kept for debug on failure."""
        self.db.rollback()
        session = self.db.get(UploadSession, session.id)
        assert session is not None
        if indexed:
            try:
                delete_chunks_by_file_id(file_id, settings=self.settings)
            except Exception:  # noqa: BLE001
                pass
        if file_row is not None and file_row.id is not None:
            existing = self.db.get(File, file_id)
            if existing is not None:
                self.db.delete(existing)
                self.db.commit()
        if minio_written:
            try:
                self.store.delete_object(object_path)
            except Exception:  # noqa: BLE001
                pass

        session.status = "failed"
        session.error_message = error[:2000]
        session.file_id = None
        session.chunk_count = None
        session.updated_at = _utcnow()
        self.db.commit()

    def _expire_if_needed(self, session: UploadSession) -> None:
        if session.status in {"completed", "cancelled", "expired", "failed", "processing"}:
            return
        expires = session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= _utcnow():
            session.status = "expired"
            session.updated_at = _utcnow()
            self.db.commit()
            self.db.refresh(session)
            try:
                self.staging.delete(str(session.id))
            except Exception:  # noqa: BLE001
                pass
