"""Postgres mirror of pipeline connectors.

Create mints ``connectors.id``, forwards it as ``callback_connector_id``, and
inserts only after the pipeline returns its own id.
``config`` is forwarded and is not a column. Sync history stays in
``connector_syncs``; a failed outbound sync is kept as history.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.connector import Connector, ConnectorSync
from app.schemas.admin_connectors import (
    ConnectorCreate,
    ConnectorOut,
    ConnectorStatusRequest,
    ConnectorSyncAccepted,
    ConnectorSyncOut,
    ConnectorUpdate,
)
from app.services.ingestion_pipeline import (
    PipelineError,
    create_connector as pipeline_create,
    sync_connector as pipeline_sync,
    update_connector as pipeline_update,
)


class AdminConnectorError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def connector_out(row: Connector) -> ConnectorOut:
    return ConnectorOut(
        id=row.id,
        type=row.type,
        name=row.name,
        enabled=row.enabled,
        schedule=row.schedule,
        pipeline_connector_id=row.pipeline_connector_id,
        status=row.status,
        last_sync_at=row.last_sync_at,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def sync_out(row: ConnectorSync) -> ConnectorSyncOut:
    return ConnectorSyncOut(
        id=row.id,
        connector_id=row.connector_id,
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        files_count=row.files_count,
        error=row.error,
    )


class AdminConnectorService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_connectors(self) -> list[ConnectorOut]:
        rows = self.db.scalars(select(Connector).order_by(Connector.created_at.desc())).all()
        return [connector_out(row) for row in rows]

    def get_connector(self, connector_id: uuid.UUID) -> ConnectorOut:
        return connector_out(self._require(connector_id))

    def create_connector(self, body: ConnectorCreate) -> ConnectorOut:
        connector_id = uuid.uuid4()
        pipeline_id = pipeline_create(
            type=body.type,
            name=body.name,
            enabled=body.enabled,
            schedule=body.schedule,
            config=body.config,
            callback_connector_id=str(connector_id),
        )
        now = _utcnow()
        row = Connector(
            id=connector_id,
            type=body.type,
            name=body.name,
            enabled=body.enabled,
            schedule=body.schedule,
            pipeline_connector_id=pipeline_id,
            status="idle" if body.enabled else "pending",
            last_sync_at=None,
            last_error=None,
            created_at=now,
            updated_at=now,
        )
        try:
            self.db.add(row)
            self.db.commit()
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise AdminConnectorError(
                502,
                "local connector insert failed; the pipeline may keep an orphan connector",
            ) from exc
        self.db.refresh(row)
        return connector_out(row)

    def update_connector(self, connector_id: uuid.UUID, body: ConnectorUpdate) -> ConnectorOut:
        row = self._require(connector_id)
        if row.pipeline_connector_id is None:
            raise AdminConnectorError(409, "connector has no pipeline id")
        fields = body.model_dump(exclude_unset=True)
        pipeline_update(row.pipeline_connector_id, fields)
        if "name" in fields:
            row.name = fields["name"]
        if "enabled" in fields:
            row.enabled = fields["enabled"]
        if "schedule" in fields:
            row.schedule = fields["schedule"]
        row.updated_at = _utcnow()
        self.db.commit()
        self.db.refresh(row)
        return connector_out(row)

    def start_sync(self, connector_id: uuid.UUID) -> ConnectorSyncAccepted:
        row = self._require(connector_id)
        if row.pipeline_connector_id is None:
            raise AdminConnectorError(409, "connector has no pipeline id")
        now = _utcnow()
        sync_row = ConnectorSync(
            id=uuid.uuid4(),
            connector_id=row.id,
            status="syncing",
            started_at=now,
        )
        pipeline_id = row.pipeline_connector_id
        row.status = "syncing"
        row.updated_at = now
        self.db.add(sync_row)
        self.db.commit()
        self.db.refresh(sync_row)
        try:
            pipeline_sync(pipeline_id)
        except PipelineError as exc:
            self._mark_sync_failed(row, sync_row, exc.detail)
            raise
        return ConnectorSyncAccepted(sync_id=sync_row.id, status="syncing")

    def list_syncs(self, connector_id: uuid.UUID) -> list[ConnectorSyncOut]:
        self._require(connector_id)
        rows = self.db.scalars(
            select(ConnectorSync)
            .where(ConnectorSync.connector_id == connector_id)
            .order_by(ConnectorSync.started_at.desc())
        ).all()
        return [sync_out(row) for row in rows]

    def apply_status(self, connector_id: uuid.UUID, body: ConnectorStatusRequest) -> ConnectorOut:
        row = self._require(connector_id)
        now = _utcnow()
        finished = body.finished_at or now
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        row.status = body.status
        row.last_error = None if body.status == "success" else body.error
        row.last_sync_at = finished
        row.updated_at = now
        sync_row = self.db.scalar(
            select(ConnectorSync)
            .where(
                ConnectorSync.connector_id == row.id,
                ConnectorSync.status == "syncing",
            )
            .order_by(ConnectorSync.started_at.desc())
            .limit(1)
        )
        if sync_row is not None:
            sync_row.status = body.status
            sync_row.finished_at = finished
            sync_row.files_count = body.files_count
            sync_row.error = body.error
        self.db.commit()
        self.db.refresh(row)
        return connector_out(row)

    def _require(self, connector_id: uuid.UUID) -> Connector:
        row = self.db.get(Connector, connector_id)
        if row is None:
            raise AdminConnectorError(404, "connector not found")
        return row

    def _mark_sync_failed(self, row: Connector, sync_row: ConnectorSync, detail: str) -> None:
        now = _utcnow()
        message = detail[:500]
        sync_row.status = "failed"
        sync_row.finished_at = now
        sync_row.error = message
        row.status = "failed"
        row.last_error = message
        row.updated_at = now
        self.db.commit()
