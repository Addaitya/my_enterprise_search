"""Successful OpenSearch query-time samples (dashboard avg query time)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SearchQueryMetric(Base):
    """OpenSearch ``took`` (ms) from a completed POST /search. No query text.

    client_hybrid: match.took + neural.took. native_hybrid: the single query took.
    """

    __tablename__ = "search_query_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    took_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
