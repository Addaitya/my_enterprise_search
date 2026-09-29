"""Assemble admin dashboard stats. OpenSearch is not queried at read time.

Avg query time is mean OpenSearch ``took`` samples already stored in Postgres
(client_hybrid = match + neural; native_hybrid = one query).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.connector import Connector
from app.models.file import File
from app.models.ingest_job import IngestJob
from app.models.search_metrics import SearchQueryMetric
from app.schemas.admin_stats import AdminStatsOut, AdminStatsPlaceholders
from app.services.minio_store import MinioStore

_NO_LAST_SYNC = "\u2014"


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


def _active_connectors(db: Session) -> int:
    value = db.scalar(select(func.count()).select_from(Connector).where(Connector.enabled.is_(True)))
    return int(value or 0)


def _ingestion_rate_docs_per_hour(db: Session) -> int:
    value = db.scalar(
        select(func.count())
        .select_from(IngestJob)
        .where(
            IngestJob.status == "completed",
            IngestJob.completed_at >= text("(now() - interval '1 hour')"),
        )
    )
    return int(value or 0)


def _last_sync(db: Session) -> str:
    value = db.scalar(select(func.max(Connector.last_sync_at)))
    if value is None:
        return _NO_LAST_SYNC
    if not isinstance(value, datetime):
        return _NO_LAST_SYNC
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def get_admin_stats(db: Session, store: MinioStore | None = None) -> AdminStatsOut:
    store = store or MinioStore()
    return AdminStatsOut(
        avg_query_time_ms=_avg_query_time_ms(db),
        total_data_ingested_bytes=store.sum_object_sizes(),
        total_docs_indexed=_total_docs_indexed(db),
        active_connectors=_active_connectors(db),
        ingestion_rate_docs_per_hour=_ingestion_rate_docs_per_hour(db),
        last_sync=_last_sync(db),
        placeholders=AdminStatsPlaceholders(
            active_connectors=False,
            ingestion_rate_docs_per_hour=False,
            last_sync=False,
        ),
    )
