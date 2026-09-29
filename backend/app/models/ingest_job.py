"""Reserve-then-complete ingest jobs. No foreign key to files.

A job is inserted before any files row exists, because files.object_store_path
is NOT NULL. file_id is allocated here and reused when the file row is written.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.file import FILE_INGESTION_TYPE_CHECK


class IngestJob(Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = (
        CheckConstraint(FILE_INGESTION_TYPE_CHECK, name="ck_ingest_jobs_ingestion_type"),
        CheckConstraint(
            "status IN ('reserved', 'completed', 'failed', 'expired')",
            name="ck_ingest_jobs_status",
        ),
        Index("ix_ingest_jobs_file_id_created_at", "file_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_store_path: Mapped[str] = mapped_column(String, nullable=False)
    ingestion_type: Mapped[str] = mapped_column(String, nullable=False)
    original_source: Mapped[str] = mapped_column(String, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
