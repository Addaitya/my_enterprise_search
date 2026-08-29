from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.identity import Group, Role, User


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint("ingestion_type IN ('local')", name="ck_files_ingestion_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    object_store_path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    file_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ingestion_type: Mapped[str] = mapped_column(String, nullable=False)
    original_source: Mapped[str | None] = mapped_column(String, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    acl_entries: Mapped[list[FileAcl]] = relationship(
        back_populates="file", passive_deletes=True
    )


class FileAcl(Base):
    """Resource-scoped file grants. Admin capability is the Keycloak realm role `admin`, not a row here.

    permission: local v1 stores viewer | editor. Later connector ingest may add owner | deleter
    via a migration that widens the CHECK (do not use a PostgreSQL ENUM).
    """

    __tablename__ = "file_acl"
    __table_args__ = (
        CheckConstraint(
            "permission IN ('viewer', 'editor')",
            name="ck_file_acl_permission",
        ),
        CheckConstraint(
            "(user_id IS NOT NULL AND role_id IS NULL AND group_id IS NULL) OR "
            "(user_id IS NULL AND role_id IS NOT NULL AND group_id IS NULL) OR "
            "(user_id IS NULL AND role_id IS NULL AND group_id IS NOT NULL)",
            name="ck_file_acl_one_principal",
        ),
        Index(
            "uq_file_acl_file_user",
            "file_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_file_acl_file_role",
            "file_id",
            "role_id",
            unique=True,
            postgresql_where=text("role_id IS NOT NULL"),
        ),
        Index(
            "uq_file_acl_file_group",
            "file_id",
            "group_id",
            unique=True,
            postgresql_where=text("group_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=True,
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="RESTRICT"),
        nullable=True,
    )
    permission: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="local = viewer | editor; connectors may add owner | deleter",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    file: Mapped[File] = relationship(back_populates="acl_entries")
    user: Mapped[User | None] = relationship()
    role: Mapped[Role | None] = relationship()
    group: Mapped[Group | None] = relationship()
