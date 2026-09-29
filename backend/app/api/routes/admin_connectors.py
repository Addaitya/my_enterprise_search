"""Admin connector control plane. The SPA does not call the pipeline."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.security import CurrentUser
from app.db.session import get_db
from app.schemas.admin_connectors import (
    ConnectorCreate,
    ConnectorOut,
    ConnectorSyncAccepted,
    ConnectorSyncOut,
    ConnectorUpdate,
)
from app.services.admin_connectors import AdminConnectorError, AdminConnectorService
from app.services.ingestion_pipeline import PipelineError

router = APIRouter(prefix="/admin", tags=["admin-connectors"])


def _service(db: Session = Depends(get_db)) -> AdminConnectorService:
    return AdminConnectorService(db)


def _http_error(exc: AdminConnectorError | PipelineError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/connectors", response_model=list[ConnectorOut])
def list_connectors(
    _admin: CurrentUser = Depends(require_admin),
    service: AdminConnectorService = Depends(_service),
) -> list[ConnectorOut]:
    return service.list_connectors()


@router.post("/connectors", response_model=ConnectorOut, status_code=status.HTTP_201_CREATED)
def create_connector(
    body: ConnectorCreate,
    _admin: CurrentUser = Depends(require_admin),
    service: AdminConnectorService = Depends(_service),
) -> ConnectorOut:
    try:
        return service.create_connector(body)
    except (AdminConnectorError, PipelineError) as exc:
        raise _http_error(exc) from exc


@router.get("/connectors/{connector_id}", response_model=ConnectorOut)
def get_connector(
    connector_id: UUID,
    _admin: CurrentUser = Depends(require_admin),
    service: AdminConnectorService = Depends(_service),
) -> ConnectorOut:
    try:
        return service.get_connector(connector_id)
    except AdminConnectorError as exc:
        raise _http_error(exc) from exc


@router.patch("/connectors/{connector_id}", response_model=ConnectorOut)
def update_connector(
    connector_id: UUID,
    body: ConnectorUpdate,
    _admin: CurrentUser = Depends(require_admin),
    service: AdminConnectorService = Depends(_service),
) -> ConnectorOut:
    try:
        return service.update_connector(connector_id, body)
    except (AdminConnectorError, PipelineError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/connectors/{connector_id}/sync",
    response_model=ConnectorSyncAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def sync_connector(
    connector_id: UUID,
    _admin: CurrentUser = Depends(require_admin),
    service: AdminConnectorService = Depends(_service),
) -> ConnectorSyncAccepted:
    try:
        return service.start_sync(connector_id)
    except (AdminConnectorError, PipelineError) as exc:
        raise _http_error(exc) from exc


@router.get("/connectors/{connector_id}/syncs", response_model=list[ConnectorSyncOut])
def list_connector_syncs(
    connector_id: UUID,
    _admin: CurrentUser = Depends(require_admin),
    service: AdminConnectorService = Depends(_service),
) -> list[ConnectorSyncOut]:
    try:
        return service.list_syncs(connector_id)
    except AdminConnectorError as exc:
        raise _http_error(exc) from exc
