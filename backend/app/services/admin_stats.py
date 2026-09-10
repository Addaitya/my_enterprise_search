"""Assemble admin dashboard stats. OpenSearch is not queried."""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.search_metrics import SearchQueryMetric
from app.schemas.admin_stats import AdminStatsOut, AdminStatsPlaceholders
from app.services.minio_store import MinioStore

PLACEHOLDER_ACTIVE_CONNECTORS = 8
PLACEHOLDER_INGESTION_RATE_DOCS_PER_HOUR = 12400
PLACEHOLDER_LAST_SYNC = "2 min ago"


def _avg_query_time_ms(db: Session) -> float | None:
    value = db.scalar(
        select(func.avg(SearchQueryMetric.took_ms)).where(
            SearchQueryMetric.created_at >= text("(now() - interval '24 hours')")
        )
    )
    if value is None:
        return None
    return float(value)


def _total_docs_indexed(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(File)) or 0)


def get_admin_stats(db: Session, store: MinioStore | None = None) -> AdminStatsOut:
    store = store or MinioStore()
    return AdminStatsOut(
        avg_query_time_ms=_avg_query_time_ms(db),
        total_data_ingested_bytes=store.sum_object_sizes(),
        total_docs_indexed=_total_docs_indexed(db),
        active_connectors=PLACEHOLDER_ACTIVE_CONNECTORS,
        ingestion_rate_docs_per_hour=PLACEHOLDER_INGESTION_RATE_DOCS_PER_HOUR,
        last_sync=PLACEHOLDER_LAST_SYNC,
        placeholders=AdminStatsPlaceholders(
            active_connectors=True,
            ingestion_rate_docs_per_hour=True,
            last_sync=True,
        ),
    )
