"""Admin file inventory, ACL, and sync jobs (Task 6b)."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.security import CurrentUser
from app.db.session import get_db
from app.models.acl_job import AclSyncJob
from app.schemas.admin_acl import (
    AclGrantOut,
    AclJobListResponse,
    AclJobOut,
    AclReplaceRequest,
    AclUpsertRequest,
    AdminFileListResponse,
    AdminFileOut,
    FileAclResponse,
)
from app.services import acl_sync, file_acl_admin
from app.services.file_acl_admin import GrantSpec

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-acl"])


def _grant_out(g: file_acl_admin.GrantView) -> AclGrantOut:
    return AclGrantOut(
        id=g.id,
        principal_type=g.principal_type,
        principal_id=g.principal_id,
        principal_name=g.principal_name,
        permission=g.permission,
    )


def _job_out(job: AclSyncJob) -> AclJobOut:
    return AclJobOut(
        id=job.id,
        file_id=job.file_id,
        status=job.status,
        total_chunks=job.total_chunks,
        updated_chunks=job.updated_chunks,
        error=job.error,
        created_by_user_id=job.created_by_user_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _commit_and_enqueue(
    db: Session,
    *,
    file_id: UUID,
    grants_view: list[file_acl_admin.GrantView],
    admin: CurrentUser,
    background: BackgroundTasks,
) -> FileAclResponse:
    """Commit ACL first (G6), then enqueue job. Enqueue fail → 503 with PG already saved (C12)."""
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("Failed to commit ACL mutate")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save ACL",
        ) from exc

    created_by = acl_sync.resolve_created_by_user_id(db, admin.sub)
    try:
        job = acl_sync.enqueue_acl_sync_job(db, file_id, created_by_user_id=created_by)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("Failed to enqueue ACL sync after PG commit")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ACL saved but sync job could not be enqueued",
        ) from exc

    background.add_task(acl_sync.run_acl_sync_job, job.id)
    return FileAclResponse(
        file_id=file_id,
        grants=[_grant_out(g) for g in grants_view],
        acl_job_id=job.id,
    )


@router.get("/files", response_model=AdminFileListResponse)
def list_admin_files(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminFileListResponse:
    items, total = file_acl_admin.list_all_files(db, limit=limit, offset=offset)
    return AdminFileListResponse(
        items=[
            AdminFileOut(
                id=i.id,
                display_name=i.display_name,
                file_type=i.file_type,
                size_bytes=i.size_bytes,
                object_store_path=i.object_store_path,
                uploaded_at=i.uploaded_at,
                updated_at=i.updated_at,
            )
            for i in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/files/{file_id}/acl", response_model=FileAclResponse)
def get_file_acl(
    file_id: UUID,
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FileAclResponse:
    grants = file_acl_admin.list_grants(db, file_id)
    return FileAclResponse(
        file_id=file_id,
        grants=[_grant_out(g) for g in grants],
        acl_job_id=None,
    )


@router.put("/files/{file_id}/acl", response_model=FileAclResponse)
def replace_file_acl(
    file_id: UUID,
    body: AclReplaceRequest,
    background: BackgroundTasks,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FileAclResponse:
    specs = [
        GrantSpec(
            principal_type=g.principal_type,
            principal_id=g.principal_id,
            permission=g.permission,
        )
        for g in body.grants
    ]
    grants = file_acl_admin.replace_all_grants(db, file_id, specs)
    return _commit_and_enqueue(
        db, file_id=file_id, grants_view=grants, admin=admin, background=background
    )


@router.post("/files/{file_id}/acl", response_model=FileAclResponse)
def upsert_file_acl(
    file_id: UUID,
    body: AclUpsertRequest,
    background: BackgroundTasks,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FileAclResponse:
    grant = GrantSpec(
        principal_type=body.principal_type,
        principal_id=body.principal_id,
        permission=body.permission,
    )
    grants = file_acl_admin.upsert_one_grant(db, file_id, grant)
    return _commit_and_enqueue(
        db, file_id=file_id, grants_view=grants, admin=admin, background=background
    )


@router.delete("/files/{file_id}/acl/{acl_id}", response_model=FileAclResponse)
def delete_file_acl(
    file_id: UUID,
    acl_id: UUID,
    background: BackgroundTasks,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FileAclResponse:
    grants = file_acl_admin.delete_grant(db, file_id, acl_id)
    return _commit_and_enqueue(
        db, file_id=file_id, grants_view=grants, admin=admin, background=background
    )


@router.get("/acl-jobs/{job_id}", response_model=AclJobOut)
def get_acl_job(
    job_id: UUID,
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AclJobOut:
    return _job_out(acl_sync.get_job_or_404(db, job_id))


@router.get("/acl-jobs", response_model=AclJobListResponse)
def list_acl_jobs(
    file_id: UUID | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AclJobListResponse:
    rows, total = acl_sync.list_jobs(
        db, file_id=file_id, status_filter=status_filter, limit=limit, offset=offset
    )
    return AclJobListResponse(
        items=[_job_out(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/acl-jobs/{job_id}/retry", response_model=AclJobOut)
def retry_acl_job(
    job_id: UUID,
    background: BackgroundTasks,
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AclJobOut:
    job = acl_sync.retry_failed_job(db, job_id)
    db.commit()
    background.add_task(acl_sync.run_acl_sync_job, job.id)
    return _job_out(job)
