"""Admin dashboard stats (ops KPIs)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.security import CurrentUser
from app.db.session import get_db
from app.schemas.admin_stats import AdminStatsOut
from app.services.admin_stats import get_admin_stats
from app.services.minio_store import MinioStatsError

router = APIRouter(prefix="/admin", tags=["admin-stats"])


@router.get("/stats", response_model=AdminStatsOut)
def admin_stats(
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminStatsOut:
    try:
        return get_admin_stats(db)
    except MinioStatsError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MinIO stats failed: {exc}",
        ) from exc
