"""File upload + view/open routes (Tasks 4–5)."""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from minio.error import S3Error
from sqlalchemy.orm import Session

from app.api.deps import require_product_user
from app.core.security import CurrentUser
from app.db.session import get_db
from app.models.file import File
from app.schemas.files import (
    CompleteUploadResponse,
    FileDetail,
    FileListItem,
    FileListResponse,
    InitiateUploadRequest,
    InitiateUploadResponse,
    PutRangeResponse,
    UploadStatusResponse,
)
from app.services.file_access import (
    content_type_for_file_type,
    display_name_from_path,
    get_file,
    list_visible_files,
    user_can_view_file,
)
from app.services.minio_store import MinioStore
from app.services.upload import UploadService, UploadServiceError

router = APIRouter(prefix="/files", tags=["files"])


def _service(db: Session = Depends(get_db)) -> UploadService:
    return UploadService(db)


def _file_to_item(row: File) -> FileListItem:
    return FileListItem(
        id=row.id,
        display_name=display_name_from_path(row.object_store_path),
        file_type=row.file_type,
        size_bytes=row.size_bytes,
        ingestion_type=row.ingestion_type,
        object_store_path=row.object_store_path,
        uploaded_at=row.uploaded_at,
        updated_at=row.updated_at,
    )


def _content_disposition(display_name: str) -> str:
    """attachment; filename=… with ASCII fallback + RFC 5987 filename*."""
    safe_ascii = "".join(c if 32 <= ord(c) < 127 and c not in '\\"' else "_" for c in display_name)
    if not safe_ascii.strip("._"):
        safe_ascii = "download"
    encoded = quote(display_name, safe="")
    return f'attachment; filename="{safe_ascii}"; filename*=UTF-8\'\'{encoded}'


# --- Upload routes (static /uploads* before /{file_id}) ---


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


# --- View / Open (Postgres ACL; MinIO stream) ---


@router.get("", response_model=FileListResponse)
def list_files(
    user: CurrentUser = Depends(require_product_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> FileListResponse:
    items, total = list_visible_files(db, user, limit=limit, offset=offset)
    return FileListResponse(
        items=[_file_to_item(row) for row in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{file_id}", response_model=FileDetail)
def get_file_metadata(
    file_id: UUID,
    user: CurrentUser = Depends(require_product_user),
    db: Session = Depends(get_db),
) -> FileDetail:
    row = get_file(db, file_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if not user_can_view_file(db, user, file_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return FileDetail.model_validate(_file_to_item(row).model_dump())


@router.get("/{file_id}/content")
def get_file_content(
    file_id: UUID,
    user: CurrentUser = Depends(require_product_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    row = get_file(db, file_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if not user_can_view_file(db, user, file_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    store = MinioStore()
    # Only stream the DB path — never a client-supplied object key (landmine 13).
    object_path = row.object_store_path
    if not store.object_exists(object_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Object not found")

    display_name = display_name_from_path(object_path)
    media_type = content_type_for_file_type(row.file_type)

    try:
        iterator = store.iter_object(object_path)
    except S3Error as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Object not found",
        ) from exc

    return StreamingResponse(
        iterator,
        media_type=media_type,
        headers={
            "Content-Disposition": _content_disposition(display_name),
            "Content-Length": str(row.size_bytes),
        },
    )
