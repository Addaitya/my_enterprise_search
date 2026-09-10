"""Persist successful POST /search OpenSearch ``took`` without blocking the response."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.models.search_metrics import SearchQueryMetric

logger = logging.getLogger(__name__)


def record_search_metric(took_ms: int) -> None:
    """Insert one OpenSearch ``took`` sample. Own session (safe for BackgroundTasks)."""
    try:
        engine = get_engine()
        with Session(bind=engine) as db:
            db.add(SearchQueryMetric(took_ms=took_ms))
            db.commit()
    except Exception:
        logger.exception("failed to persist search_query_metrics took_ms=%s", took_ms)
