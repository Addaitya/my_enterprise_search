"""upload_sessions for resumable ingest

Revision ID: a1b2c3d4e5f6
Revises: 68a730544554
Create Date: 2026-08-29

Adds upload_sessions for Drive-style resumable uploads. Does not alter `files`
(no original_filename / status / uploaded_by — data-model G8).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "68a730544554"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upload_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False, comment="JWT sub of initiating user"),
        sa.Column("safe_filename", sa.String(), nullable=False),
        sa.Column("file_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("bytes_received", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="initiated"),
        sa.Column("staging_path", sa.String(), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('initiated', 'uploading', 'processing', 'completed', 'failed', 'expired', 'cancelled')",
            name="ck_upload_sessions_status",
        ),
        sa.CheckConstraint(
            "file_type IN ('pdf', 'txt', 'csv')",
            name="ck_upload_sessions_file_type",
        ),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_upload_sessions_user_id", "upload_sessions", ["user_id"])
    op.create_index("ix_upload_sessions_status", "upload_sessions", ["status"])
    op.create_index("ix_upload_sessions_expires_at", "upload_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_upload_sessions_expires_at", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_status", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_user_id", table_name="upload_sessions")
    op.drop_table("upload_sessions")
