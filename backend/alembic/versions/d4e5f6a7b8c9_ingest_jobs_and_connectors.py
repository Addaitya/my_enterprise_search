"""ingest jobs, connectors, and widened files.ingestion_type

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-28

Reserve ingest_jobs before a files row exists, so file_id is not a foreign key.
Connector rows store no source secrets. ingestion_type values match
app.models.file.FILE_INGESTION_TYPES (plain text, not a PostgreSQL ENUM).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INGESTION_TYPE_CHECK = (
    "ingestion_type IN ("
    "'local', 'sharepoint', 'google_drive', 's3', 'postgresql', 'oracle', "
    "'sqlserver', 'salesforce', 'azure', 'gcs', 'email', 'box', 'sap', 'pipeline'"
    ")"
)


def upgrade() -> None:
    op.drop_constraint("ck_files_ingestion_type", "files", type_="check")
    op.create_check_constraint(
        "ck_files_ingestion_type",
        "files",
        _INGESTION_TYPE_CHECK,
    )
    op.create_index(
        "uq_files_ingestion_source",
        "files",
        ["ingestion_type", "original_source"],
        unique=True,
        postgresql_where=sa.text("original_source IS NOT NULL"),
    )

    op.create_table(
        "ingest_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_store_path", sa.String(), nullable=False),
        sa.Column("ingestion_type", sa.String(), nullable=False),
        sa.Column("original_source", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_INGESTION_TYPE_CHECK, name="ck_ingest_jobs_ingestion_type"),
        sa.CheckConstraint(
            "status IN ('reserved', 'completed', 'failed', 'expired')",
            name="ck_ingest_jobs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ingest_jobs_file_id_created_at",
        "ingest_jobs",
        ["file_id", "created_at"],
    )

    op.create_table(
        "connectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("schedule", sa.Text(), nullable=True),
        sa.Column("pipeline_connector_id", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'idle', 'syncing', 'success', 'failed')",
            name="ck_connectors_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "connector_syncs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connector_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("files_count", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('syncing', 'success', 'failed')",
            name="ck_connector_syncs_status",
        ),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_connector_syncs_connector_id",
        "connector_syncs",
        ["connector_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_connector_syncs_connector_id", table_name="connector_syncs")
    op.drop_table("connector_syncs")
    op.drop_table("connectors")
    op.drop_index("ix_ingest_jobs_file_id_created_at", table_name="ingest_jobs")
    op.drop_table("ingest_jobs")
    op.drop_index("uq_files_ingestion_source", table_name="files")
    op.drop_constraint("ck_files_ingestion_type", "files", type_="check")
    op.create_check_constraint(
        "ck_files_ingestion_type",
        "files",
        "ingestion_type IN ('local')",
    )
