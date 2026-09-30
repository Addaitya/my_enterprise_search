"""A shorter complete drops indexed chunks whose seq is absent from the body."""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.services.internal_ingest import InternalIngestService
from app.services.opensearch_ingest import delete_omitted_chunks


class _Settings:
    opensearch_index = "enterprise-search-chunks"


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.is_error = status_code >= 400
        self.text = "nope"

    def json(self) -> dict:
        return self._payload


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict, dict]] = []

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def post(self, path: str, *, params: dict, json: dict) -> _Response:
        self.calls.append((path, params, json))
        return self.response


class _Store:
    def stat_object_size(self, path: str) -> int:
        del path
        return 4


class _Db:
    def __init__(self) -> None:
        self.deleted: list[object] = []
        self.committed = False

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        return None

    def delete(self, row: object) -> None:
        self.deleted.append(row)


class _Row:
    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self.uploaded_at = now
        self.updated_at = now


class DeleteOmittedChunksTests(unittest.TestCase):
    def test_posts_file_filter_and_must_not_seqs(self) -> None:
        file_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
        client = _Client(_Response(200, {"version_conflicts": 0, "failures": []}))
        with patch("app.services.opensearch_ingest._admin_client", return_value=client):
            delete_omitted_chunks(file_id, [0, 2], settings=_Settings())  # type: ignore[arg-type]

        self.assertEqual(len(client.calls), 1)
        path, params, body = client.calls[0]
        self.assertEqual(path, "/enterprise-search-chunks/_delete_by_query")
        self.assertEqual(params, {"refresh": "true", "conflicts": "proceed"})
        self.assertEqual(
            body,
            {
                "query": {
                    "bool": {
                        "filter": [{"term": {"file_id": str(file_id)}}],
                        "must_not": [{"terms": {"chunk_seq": [0, 2]}}],
                    }
                }
            },
        )

    def test_version_conflicts_raise(self) -> None:
        client = _Client(_Response(200, {"version_conflicts": 1, "failures": []}))
        with patch("app.services.opensearch_ingest._admin_client", return_value=client):
            with self.assertRaises(RuntimeError):
                delete_omitted_chunks(
                    uuid.uuid4(),
                    [0],
                    settings=_Settings(),  # type: ignore[arg-type]
                )

    def test_empty_keep_list_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            delete_omitted_chunks(uuid.uuid4(), [], settings=_Settings())  # type: ignore[arg-type]


class CompleteDropsOmittedSeqsTests(unittest.TestCase):
    def test_shorter_body_drops_omitted_seqs_and_keeps_the_file(self) -> None:
        file_id = uuid.uuid4()
        job = SimpleNamespace(
            id=uuid.uuid4(),
            file_id=file_id,
            status="reserved",
            size_bytes=4,
            object_store_path="files/pipeline/x/a.log",
            ingestion_type="pipeline",
            original_source="s3://bucket/a.log",
        )
        db = _Db()
        service = InternalIngestService(db, settings=_Settings(), store=_Store())  # type: ignore[arg-type]
        with (
            patch.object(service, "_latest_job_for_file", return_value=job),
            patch.object(service, "_upsert_file", return_value=_Row()),
            patch(
                "app.services.internal_ingest.recompute_allowed_names",
                return_value=([], []),
            ),
            patch("app.services.internal_ingest.bulk_index_chunks") as bulk,
            patch("app.services.internal_ingest.delete_omitted_chunks") as omitted,
            patch("app.services.internal_ingest.delete_chunks_by_file_id") as full_delete,
        ):
            result = service.complete(
                file_id,
                size_bytes=4,
                file_type="log",
                chunks=[(2, "tail"), (0, "head")],
            )

        self.assertEqual(result.chunk_count, 2)
        self.assertEqual(result.status, "completed")
        bulk.assert_called_once()
        omitted.assert_called_once_with(file_id, [0, 2], settings=service.settings)
        full_delete.assert_not_called()
        self.assertEqual(db.deleted, [])
        self.assertTrue(db.committed)
        self.assertEqual(job.status, "completed")
