from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

UPLOAD_SESSION_STATUSES = (
    "initiated",
    "uploading",
    "processing",
    "completed",
    "failed",
    "expired",
    "cancelled",
)


class UploadSession(Base):
    """Resumable upload state. Not a column on `files` (data-model G8)."""

    __tablename__ = "upload_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('initiated', 'uploading', 'processing', 'completed', 'failed', 'expired', 'cancelled')",
            name="ck_upload_sessions_status",
        ),
        CheckConstraint(
            "file_type IN ('pdf', 'txt', 'csv')",
            name="ck_upload_sessions_file_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, nullable=False, comment="JWT sub of initiating user")
    safe_filename: Mapped[str] = mapped_column(String, nullable=False)
    file_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bytes_received: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="initiated")
    staging_path: Mapped[str] = mapped_column(String, nullable=False)
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
    )
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
