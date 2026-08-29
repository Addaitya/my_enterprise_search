"""Resumable file upload routes (Task 4 ingest API)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import require_product_user
from app.core.security import CurrentUser
from app.db.session import get_db
from app.schemas.files import (
    CompleteUploadResponse,
    InitiateUploadRequest,
    InitiateUploadResponse,
    PutRangeResponse,
    UploadStatusResponse,
)
from app.services.upload import UploadService, UploadServiceError

router = APIRouter(prefix="/files", tags=["files"])


def _service(db: Session = Depends(get_db)) -> UploadService:
    return UploadService(db)


@router.post("/uploads", response_model=InitiateUploadResponse, status_code=201)
def initiate_upload(
    body: InitiateUploadRequest,
    user: CurrentUser = Depends(require_product_user),
    service: UploadService = Depends(_service),
) -> InitiateUploadResponse:
    try:
        session = service.initiate(
            user_sub=user.sub,
            filename=body.filename,
            size_bytes=body.size_bytes,
            content_type=body.content_type,
        )
    except UploadServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return InitiateUploadResponse(
        upload_id=session.id,
        upload_url=f"/api/files/uploads/{session.id}",
        status=session.status,
        size_bytes=session.size_bytes,
        bytes_received=session.bytes_received,
        expires_at=session.expires_at,
    )


@router.get("/uploads/{upload_id}", response_model=UploadStatusResponse)
def upload_status(
    upload_id: UUID,
    user: CurrentUser = Depends(require_product_user),
    service: UploadService = Depends(_service),
) -> UploadStatusResponse:
    try:
        session = service.get_owned(upload_id, user.sub)
    except UploadServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return UploadStatusResponse(
        upload_id=session.id,
        status=session.status,
        file_type=session.file_type,
        size_bytes=session.size_bytes,
        bytes_received=session.bytes_received,
        file_id=session.file_id,
        chunk_count=session.chunk_count,
        error=session.error_message,
        expires_at=session.expires_at,
    )


@router.put("/uploads/{upload_id}")
async def put_upload_range(
    upload_id: UUID,
    request: Request,
    user: CurrentUser = Depends(require_product_user),
    service: UploadService = Depends(_service),
    content_range: str | None = Header(default=None, alias="Content-Range"),
) -> Response:
    body = await request.body()
    try:
        session = service.put_range(
            upload_id=upload_id,
            user_sub=user.sub,
            content_range=content_range,
            body=body,
        )
    except UploadServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    payload = {
        "status": session.status,
        "bytes_received": session.bytes_received,
    }
    if session.bytes_received < session.size_bytes:
        headers: dict[str, str] = {}
        if session.bytes_received > 0:
            headers["Range"] = f"bytes=0-{session.bytes_received - 1}"
        return JSONResponse(status_code=308, content=payload, headers=headers)

    return JSONResponse(
        status_code=200,
        content=PutRangeResponse(
            status=session.status,
            bytes_received=session.bytes_received,
        ).model_dump(),
    )


@router.post("/uploads/{upload_id}/complete", response_model=CompleteUploadResponse, status_code=201)
def complete_upload(
    upload_id: UUID,
    user: CurrentUser = Depends(require_product_user),
    service: UploadService = Depends(_service),
) -> CompleteUploadResponse:
    try:
        session, file_row = service.complete(upload_id=upload_id, user_sub=user.sub)
    except UploadServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return CompleteUploadResponse(
        upload_id=session.id,
        status=session.status,
        id=file_row.id,
        file_type=file_row.file_type,
        size_bytes=file_row.size_bytes,
        object_store_path=file_row.object_store_path,
        ingestion_type=file_row.ingestion_type,
        original_source=file_row.original_source,
        chunk_count=session.chunk_count or 0,
        uploaded_at=file_row.uploaded_at,
    )


@router.delete("/uploads/{upload_id}", status_code=204)
def cancel_upload(
    upload_id: UUID,
    user: CurrentUser = Depends(require_product_user),
    service: UploadService = Depends(_service),
) -> Response:
    try:
        service.cancel(upload_id=upload_id, user_sub=user.sub)
    except UploadServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return Response(status_code=204)
