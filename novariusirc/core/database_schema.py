"""SQLAlchemy Core metadata shared by migrations and database services."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

instance_metadata = Table(
    "instance_metadata",
    metadata,
    Column("key", String(128), primary_key=True),
    Column("value", Text, nullable=False),
)

roles = Table(
    "roles",
    metadata,
    Column("name", String(32), primary_key=True),
    Column("rank", Integer, nullable=False, unique=True),
)

role_bindings = Table(
    "role_bindings",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("role_name", String(32), ForeignKey("roles.name"), nullable=False),
    Column("binding_type", String(32), nullable=False),
    Column("binding_value", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

feed_states = Table(
    "feed_states",
    metadata,
    Column("feed_url", Text, primary_key=True),
    Column("etag", Text),
    Column("last_modified", Text),
    Column("seen_ids", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
