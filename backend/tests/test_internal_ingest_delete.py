"""DELETE /internal/ingest/files/{file_id} removes the file and its indexed data."""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from app.models.file import File
from app.models.ingest_job import IngestJob
from app.services.internal_ingest import InternalIngestError, InternalIngestService


class _Store:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_object(self, object_store_path: str) -> None:
        self.deleted.append(object_store_path)


class _ScalarResult:
    def __init__(self, rows: list[IngestJob]) -> None:
        self._rows = rows

    def all(self) -> list[IngestJob]:
        return list(self._rows)


class _Session:
    def __init__(self, files: list[File], jobs: list[IngestJob]) -> None:
        self.files = {row.id: row for row in files}
        self.jobs = list(jobs)
        self.deleted: list[File] = []
        self.committed = False

    def get(self, model: type, key: uuid.UUID) -> File | None:
        del model
        return self.files.get(key)

    def delete(self, row: File) -> None:
        self.deleted.append(row)
        self.files.pop(row.id, None)

    def scalars(self, stmt: object) -> _ScalarResult:
        del stmt
        return _ScalarResult(self.jobs)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        return None


def _file(file_id: uuid.UUID, path: str) -> File:
    now = datetime.now(timezone.utc)
    return File(
        id=file_id,
        object_store_path=path,
        file_type="log",
        size_bytes=5,
        ingestion_type="pipeline",
        original_source="s3://bucket/a.log",
        uploaded_at=now,
        updated_at=now,
    )


def _job(
    file_id: uuid.UUID,
    *,
    status: str,
    path: str,
) -> IngestJob:
    now = datetime.now(timezone.utc)
    return IngestJob(
        id=uuid.uuid4(),
        file_id=file_id,
        object_store_path=path,
        ingestion_type="pipeline",
        original_source="s3://bucket/a.log",
        filename="a.log",
        size_bytes=5,
        status=status,
        created_at=now,
        updated_at=now,
        completed_at=now if status == "completed" else None,
    )


class DeleteFileTests(unittest.TestCase):
    def test_removes_file_chunks_and_objects_and_expires_open_jobs(self) -> None:
        file_id = uuid.uuid4()
        current = f"files/pipeline/{file_id}/a.log"
        pending = f"files/pipeline/{file_id}/b.log"
        row = _file(file_id, current)
        completed = _job(file_id, status="completed", path=current)
        reserved = _job(file_id, status="reserved", path=pending)
        failed = _job(file_id, status="failed", path=pending)
        session = _Session([row], [completed, reserved, failed])
        store = _Store()
        service = InternalIngestService(session, settings=object(), store=store)  # type: ignore[arg-type]

        with patch("app.services.internal_ingest.delete_chunks_by_file_id") as chunks:
            service.delete_file(file_id)

        chunks.assert_called_once_with(file_id, settings=service.settings)
        self.assertCountEqual(store.deleted, [current, pending])
        self.assertEqual(session.deleted, [row])
        self.assertIsNone(session.files.get(file_id))
        self.assertEqual(completed.status, "completed")
        self.assertEqual(reserved.status, "expired")
        self.assertEqual(failed.status, "expired")
        self.assertTrue(session.committed)

    def test_second_delete_after_the_row_is_gone_succeeds(self) -> None:
        file_id = uuid.uuid4()
        path = f"files/pipeline/{file_id}/a.log"
        row = _file(file_id, path)
        completed = _job(file_id, status="completed", path=path)
        session = _Session([row], [completed])
        store = _Store()
        service = InternalIngestService(session, settings=object(), store=store)  # type: ignore[arg-type]

        with patch("app.services.internal_ingest.delete_chunks_by_file_id"):
            service.delete_file(file_id)
            service.delete_file(file_id)

        self.assertEqual(session.deleted, [row])
        self.assertEqual(completed.status, "completed")
        self.assertTrue(session.committed)

    def test_unknown_id_is_404(self) -> None:
        session = _Session([], [])
        service = InternalIngestService(session, settings=object(), store=_Store())  # type: ignore[arg-type]
        with patch("app.services.internal_ingest.delete_chunks_by_file_id") as chunks:
            with self.assertRaises(InternalIngestError) as caught:
                service.delete_file(uuid.uuid4())
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(caught.exception.detail, "Ingest job not found")
        chunks.assert_not_called()
        self.assertEqual(session.deleted, [])
        self.assertFalse(session.committed)

    def test_file_without_an_ingest_job_is_left_in_place(self) -> None:
        file_id = uuid.uuid4()
        row = _file(file_id, f"local/{file_id}/notes.txt")
        session = _Session([row], [])
        store = _Store()
        service = InternalIngestService(session, settings=object(), store=store)  # type: ignore[arg-type]
        with patch("app.services.internal_ingest.delete_chunks_by_file_id") as chunks:
            with self.assertRaises(InternalIngestError) as caught:
                service.delete_file(file_id)
        self.assertEqual(caught.exception.status_code, 404)
        chunks.assert_not_called()
        self.assertEqual(store.deleted, [])
        self.assertEqual(session.deleted, [])
        self.assertIs(session.files[file_id], row)

    def test_index_failure_is_502_and_keeps_the_row(self) -> None:
        file_id = uuid.uuid4()
        path = f"files/pipeline/{file_id}/a.log"
        row = _file(file_id, path)
        reserved = _job(file_id, status="reserved", path=path)
        session = _Session([row], [reserved])
        store = _Store()
        service = InternalIngestService(session, settings=object(), store=store)  # type: ignore[arg-type]
        with patch(
            "app.services.internal_ingest.delete_chunks_by_file_id",
            side_effect=RuntimeError("down"),
        ):
            with self.assertRaises(InternalIngestError) as caught:
                service.delete_file(file_id)
        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(caught.exception.detail, "search index unavailable")
        self.assertEqual(store.deleted, [])
        self.assertEqual(session.deleted, [])
        self.assertIs(session.files[file_id], row)
        self.assertEqual(reserved.status, "reserved")
        self.assertFalse(session.committed)
