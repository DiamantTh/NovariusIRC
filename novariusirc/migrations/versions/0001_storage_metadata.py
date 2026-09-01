"""Create the initial persistent storage metadata table.

Revision ID: 0001_storage_metadata
Revises:
Create Date: 2026-09-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_storage_metadata"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("instance_metadata"):
        op.create_table(
            "instance_metadata",
            sa.Column("key", sa.String(length=128), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("key"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("instance_metadata"):
        op.drop_table("instance_metadata")
