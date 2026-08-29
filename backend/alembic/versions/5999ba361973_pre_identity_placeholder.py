"""Placeholder for leftover out-of-tree revision already applied locally.

Revision ID: 5999ba361973
Revises:
Create Date: 2026-08-27

The local `app` database was stamped with this id from an experimental schema
(integer role ids, `permissions` / `file_permissions`, `users.keycloak_id`)
that is not in git. Upgrade is a no-op: those empty leftover tables are dropped
in the next revision. Fresh databases also no-op here, then create the real
schema in `68a730544554`.
"""

from typing import Sequence, Union

revision: str = "5999ba361973"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
