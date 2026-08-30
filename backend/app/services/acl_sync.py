"""Enqueue + run OpenSearch allowed_* sync jobs (Task 6b / G2 / G6).

Postgres first, then job. Worker uses basic OpenSearch ``admin`` only.
On app startup: mark ``running`` → ``failed`` with ``interrupted``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from app.models.acl_job import AclSyncJob
from app.models.identity import User
from app.services.file_acl_admin import recompute_allowed_names

logger = logging.getLogger(__name__)


def resolve_created_by_user_id(db: Session, keycloak_sub: str | None) -> uuid.UUID | None:
    if not keycloak_sub:
        return None
    try:
        uid = uuid.UUID(keycloak_sub)
    except ValueError:
        return None
    user = db.get(User, uid)
    return user.id if user is not None else None


def enqueue_acl_sync_job(
    db: Session,
    file_id: uuid.UUID,
    *,
    created_by_user_id: uuid.UUID | None = None,
) -> AclSyncJob:
    """Insert a queued job. Caller must commit the surrounding transaction."""
    job = AclSyncJob(
        id=uuid.uuid4(),
        file_id=file_id,
        status="queued",
        created_by_user_id=created_by_user_id,
    )
    db.add(job)
    db.flush()
    return job


def get_job_or_404(db: Session, job_id: uuid.UUID) -> AclSyncJob:
    job = db.get(AclSyncJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ACL sync job not found")
    return job


def list_jobs(
    db: Session,
    *,
    file_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AclSyncJob], int]:
    from sqlalchemy import func

    stmt = select(AclSyncJob)
    count_stmt = select(func.count()).select_from(AclSyncJob)
    if file_id is not None:
        stmt = stmt.where(AclSyncJob.file_id == file_id)
        count_stmt = count_stmt.where(AclSyncJob.file_id == file_id)
    if status_filter is not None:
        stmt = stmt.where(AclSyncJob.status == status_filter)
        count_stmt = count_stmt.where(AclSyncJob.status == status_filter)
    total = db.scalar(count_stmt) or 0
    rows = list(
        db.scalars(
            stmt.order_by(AclSyncJob.created_at.desc()).limit(limit).offset(offset)
        ).all()
    )
    return rows, int(total)


def retry_failed_job(db: Session, job_id: uuid.UUID) -> AclSyncJob:
    job = get_job_or_404(db, job_id)
    if job.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed jobs can be retried",
        )
    job.status = "queued"
    job.error = None
    job.total_chunks = None
    job.updated_chunks = None
    job.started_at = None
    job.finished_at = None
    job.updated_at = datetime.now(timezone.utc)
    db.flush()
    return job


def mark_interrupted_running_jobs() -> int:
    """Startup: any ``running`` job was cut off — mark failed with interrupted."""
    engine = get_engine()
    with Session(bind=engine) as db:
        result = db.execute(
            update(AclSyncJob)
            .where(AclSyncJob.status == "running")
            .values(
                status="failed",
                error="interrupted",
                finished_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        count = result.rowcount or 0
        if count:
            logger.warning("Marked %s acl_sync_jobs as failed (interrupted)", count)
        return count


def _os_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        base_url=settings.opensearch_url,
        verify=settings.opensearch_verify_certs,
        auth=("admin", settings.opensearch_initial_admin_password),
        timeout=120.0,
    )


def _count_chunks(client: httpx.Client, file_id: uuid.UUID) -> int:
    settings = get_settings()
    response = client.post(
        f"/{settings.opensearch_index}/_count",
        json={"query": {"term": {"file_id": str(file_id)}}},
    )
    if response.is_error:
        raise RuntimeError(f"OS count failed: {response.status_code} {response.text}")
    return int(response.json().get("count") or 0)


def update_by_query_allowed(
    file_id: uuid.UUID,
    *,
    allowed_roles: list[str],
    allowed_groups: list[str],
) -> dict[str, Any]:
    """Promote G3 seed shape: painless set both arrays, refresh=true, basic admin."""
    settings = get_settings()
    body: dict[str, Any] = {
        "query": {"term": {"file_id": str(file_id)}},
        "script": {
            "lang": "painless",
            "source": (
                "ctx._source.allowed_roles = params.roles; "
                "ctx._source.allowed_groups = params.groups;"
            ),
            "params": {"roles": allowed_roles, "groups": allowed_groups},
        },
    }
    with _os_client() as client:
        total = _count_chunks(client, file_id)
        response = client.post(
            f"/{settings.opensearch_index}/_update_by_query",
            params={"refresh": "true"},
            json=body,
        )
        if response.is_error:
            raise RuntimeError(
                f"update_by_query file_id={file_id}: {response.status_code} {response.text}"
            )
        payload = response.json()
        updated = int(payload.get("updated") or 0)
        return {"total_chunks": total, "updated_chunks": updated, "raw": payload}


def run_acl_sync_job(job_id: uuid.UUID) -> None:
    """Background worker: recompute names from PG, then update_by_query.

    Opens its own session. Safe to call from FastAPI BackgroundTasks.
    """
    engine = get_engine()
    with Session(bind=engine) as db:
        job = db.get(AclSyncJob, job_id)
        if job is None:
            logger.error("acl sync job %s missing", job_id)
            return
        if job.status not in ("queued",):
            logger.info("acl sync job %s status=%s — skip", job_id, job.status)
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.updated_at = job.started_at
        job.error = None
        db.commit()

        file_id = job.file_id
        try:
            allowed_roles, allowed_groups = recompute_allowed_names(db, file_id)
            result = update_by_query_allowed(
                file_id,
                allowed_roles=allowed_roles,
                allowed_groups=allowed_groups,
            )
            job = db.get(AclSyncJob, job_id)
            if job is None:
                return
            job.status = "succeeded"
            job.total_chunks = result["total_chunks"]
            job.updated_chunks = result["updated_chunks"]
            job.error = None
            job.finished_at = datetime.now(timezone.utc)
            job.updated_at = job.finished_at
            db.commit()
            logger.info(
                "acl sync job %s succeeded file_id=%s updated=%s",
                job_id,
                file_id,
                result["updated_chunks"],
            )
        except Exception as exc:  # noqa: BLE001 — persist failure on job
            logger.exception("acl sync job %s failed", job_id)
            db.rollback()
            job = db.get(AclSyncJob, job_id)
            if job is None:
                return
            job.status = "failed"
            job.error = str(exc)[:4000]
            job.finished_at = datetime.now(timezone.utc)
            job.updated_at = job.finished_at
            db.commit()
