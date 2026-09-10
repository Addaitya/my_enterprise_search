"""search_query_metrics for dashboard avg query time (last 24 hours)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-10

Unbounded latency samples from successful POST /search. Dashboard AVG
filters last 24 hours at read time. No query text is stored.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "search_query_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("took_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_search_query_metrics_created_at",
        "search_query_metrics",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_search_query_metrics_created_at", table_name="search_query_metrics")
    op.drop_table("search_query_metrics")
