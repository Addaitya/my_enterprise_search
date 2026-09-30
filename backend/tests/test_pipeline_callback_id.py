"""Pipeline create forwards this API's connector UUID. Sync stays an empty body."""

from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import UUID

import httpx

from app.schemas.admin_connectors import ConnectorCreate
from app.services.admin_connectors import AdminConnectorService
from app.services.ingestion_pipeline import PipelineError, create_connector, sync_connector


class _Settings:
    ingestion_pipeline_url = "http://pipeline.test"
    ingestion_pipeline_timeout_seconds = 10.0


class PipelineCreateBodyTests(unittest.TestCase):
    def test_create_sends_callback_connector_id(self) -> None:
        callback_id = "11111111-1111-1111-1111-111111111111"
        captured: dict[str, object] = {}

        def fake_request(method: str, url: str, *, json: dict, timeout: float) -> httpx.Response:
            captured["method"] = method
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return httpx.Response(200, json={"id": "pipe-1"})

        with patch("app.services.ingestion_pipeline.get_settings", return_value=_Settings()):
            with patch("app.services.ingestion_pipeline.httpx.request", side_effect=fake_request):
                pipeline_id = create_connector(
                    type="s3",
                    name="bucket",
                    enabled=False,
                    schedule=None,
                    config={"password": "secret"},
                    callback_connector_id=callback_id,
                )

        self.assertEqual(pipeline_id, "pipe-1")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["url"], "http://pipeline.test/connectors")
        self.assertEqual(
            captured["json"],
            {
                "type": "s3",
                "name": "bucket",
                "enabled": False,
                "schedule": None,
                "config": {"password": "secret"},
                "callback_connector_id": callback_id,
            },
        )

    def test_sync_body_stays_empty(self) -> None:
        captured: dict[str, object] = {}

        def fake_request(method: str, url: str, *, json: dict, timeout: float) -> httpx.Response:
            captured["method"] = method
            captured["url"] = url
            captured["json"] = json
            return httpx.Response(202, json={})

        with patch("app.services.ingestion_pipeline.get_settings", return_value=_Settings()):
            with patch("app.services.ingestion_pipeline.httpx.request", side_effect=fake_request):
                sync_connector("pipe-1")

        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["url"], "http://pipeline.test/connectors/pipe-1/sync")
        self.assertEqual(captured["json"], {})


class _Session:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)

    def commit(self) -> None:
        return None

    def refresh(self, row: object) -> None:
        return None

    def rollback(self) -> None:
        return None


class CreateMintsCallbackIdTests(unittest.TestCase):
    def test_insert_uses_the_id_sent_to_the_pipeline(self) -> None:
        session = _Session()
        seen: dict[str, object] = {}

        def fake_create(**kwargs: object) -> str:
            seen.update(kwargs)
            return "pipe-manual"

        body = ConnectorCreate(
            type="s3",
            name="manual-stub",
            enabled=False,
            config={"password": "secret"},
        )
        with patch("app.services.admin_connectors.pipeline_create", side_effect=fake_create):
            created = AdminConnectorService(session).create_connector(body)  # type: ignore[arg-type]

        self.assertEqual(len(session.added), 1)
        row = session.added[0]
        self.assertEqual(seen["callback_connector_id"], str(created.id))
        self.assertEqual(row.id, created.id)
        self.assertEqual(UUID(str(seen["callback_connector_id"])), created.id)
        self.assertEqual(created.pipeline_connector_id, "pipe-manual")
        self.assertNotIn("config", created.model_fields_set)

    def test_pipeline_error_inserts_nothing(self) -> None:
        session = _Session()

        def fake_create(**kwargs: object) -> str:
            raise PipelineError(502, "ingestion pipeline unreachable")

        body = ConnectorCreate(type="s3", name="manual-stub", enabled=True, config={})
        with patch("app.services.admin_connectors.pipeline_create", side_effect=fake_create):
            with self.assertRaises(PipelineError):
                AdminConnectorService(session).create_connector(body)  # type: ignore[arg-type]

        self.assertEqual(session.added, [])


if __name__ == "__main__":
    unittest.main()
