"""SQLAlchemy Core metadata shared by migrations and database services."""

from __future__ import annotations

from sqlalchemy import Column, MetaData, String, Table, Text

metadata = MetaData()

instance_metadata = Table(
    "instance_metadata",
    metadata,
    Column("key", String(128), primary_key=True),
    Column("value", Text, nullable=False),
)
