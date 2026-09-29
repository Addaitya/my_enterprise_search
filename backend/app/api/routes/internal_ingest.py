"""Machine ingest routes. Pipeline writes bytes; this API reserves and completes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_ingest_service
from app.core.security import CurrentUser
from app.db.session import get_db
from app.schemas.admin_connectors import ConnectorOut, ConnectorStatusRequest
from app.schemas.internal_ingest import (
    CompleteIngestRequest,
    CompleteIngestResponse,
    ReserveIngestRequest,
    ReserveIngestResponse,
)
from app.services.admin_connectors import AdminConnectorError, AdminConnectorService
from app.services.internal_ingest import InternalIngestError, InternalIngestService

router = APIRouter(prefix="/internal", tags=["internal-ingest"])


def _service(db: Session = Depends(get_db)) -> InternalIngestService:
    return InternalIngestService(db)


def _connectors(db: Session = Depends(get_db)) -> AdminConnectorService:
    return AdminConnectorService(db)


def _http_error(exc: InternalIngestError | AdminConnectorError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/ingest/files", response_model=ReserveIngestResponse, status_code=201)
def reserve_ingest_file(
    body: ReserveIngestRequest,
    _user: CurrentUser = Depends(require_ingest_service),
    service: InternalIngestService = Depends(_service),
) -> ReserveIngestResponse:
    try:
        result = service.reserve(
            filename=body.filename,
            size_bytes=body.size_bytes,
            ingestion_type=body.ingestion_type,
            original_source=body.original_source,
            content_type=body.content_type,
        )
    except InternalIngestError as exc:
        raise _http_error(exc) from exc
    return ReserveIngestResponse(
        file_id=result.file_id,
        object_store_path=result.object_store_path,
        upload_url=result.upload_url,
        expires_at=result.expires_at,
    )


@router.post(
    "/ingest/files/{file_id}/complete",
    response_model=CompleteIngestResponse,
    status_code=201,
)
def complete_ingest_file(
    file_id: UUID,
    body: CompleteIngestRequest,
    _user: CurrentUser = Depends(require_ingest_service),
    service: InternalIngestService = Depends(_service),
) -> CompleteIngestResponse:
    try:
        result = service.complete(
            file_id,
            size_bytes=body.size_bytes,
            file_type=body.file_type,
            chunks=[(chunk.seq, chunk.content) for chunk in body.chunks],
        )
    except InternalIngestError as exc:
        raise _http_error(exc) from exc
    return CompleteIngestResponse(
        file_id=result.file_id,
        status=result.status,
        object_store_path=result.object_store_path,
        file_type=result.file_type,
        size_bytes=result.size_bytes,
        ingestion_type=result.ingestion_type,
        chunk_count=result.chunk_count,
    )


@router.post("/connectors/{connector_id}/status", response_model=ConnectorOut)
def connector_status(
    connector_id: UUID,
    body: ConnectorStatusRequest,
    _user: CurrentUser = Depends(require_ingest_service),
    service: AdminConnectorService = Depends(_connectors),
) -> ConnectorOut:
    try:
        return service.apply_status(connector_id, body)
    except AdminConnectorError as exc:
        raise _http_error(exc) from exc
