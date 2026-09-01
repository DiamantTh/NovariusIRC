"""Create role bindings and persistent feed state.

Revision ID: 0002_persistent_core_state
Revises: 0001_storage_metadata
Create Date: 2026-09-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_persistent_core_state"
down_revision = "0001_storage_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
        sa.UniqueConstraint("rank"),
    )
    op.bulk_insert(
        sa.table(
            "roles",
            sa.column("name", sa.String()),
            sa.column("rank", sa.Integer()),
        ),
        [
            {"name": "user", "rank": 0},
            {"name": "admin", "rank": 10},
            {"name": "owner", "rank": 20},
        ],
    )
    op.create_table(
        "role_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("role_name", sa.String(length=32), nullable=False),
        sa.Column("binding_type", sa.String(length=32), nullable=False),
        sa.Column("binding_value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["role_name"], ["roles.name"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_role_bindings_lookup",
        "role_bindings",
        ["binding_type", "role_name"],
    )
    op.create_table(
        "feed_states",
        sa.Column("feed_url", sa.Text(), nullable=False),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("last_modified", sa.Text(), nullable=True),
        sa.Column("seen_ids", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("feed_url"),
    )


def downgrade() -> None:
    op.drop_table("feed_states")
    op.drop_index("ix_role_bindings_lookup", table_name="role_bindings")
    op.drop_table("role_bindings")
    op.drop_table("roles")
