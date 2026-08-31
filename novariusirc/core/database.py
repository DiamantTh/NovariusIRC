"""Database backend registry and SQLite schema management."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import DatabaseConfig

SCHEMA_VERSION = 1


class DatabaseError(RuntimeError):
    """Base exception for database setup and validation failures."""


class DatabaseBackendUnavailable(DatabaseError):
    """Raised when a known backend has no installed implementation."""


@dataclass(frozen=True)
class BackendSpec:
    name: str
    aliases: tuple[str, ...] = ()
    implemented: bool = False
    description: str = ""


BACKENDS = (
    BackendSpec("sqlite", ("sqlite3",), True, "SQLite 3"),
    BackendSpec("postgresql", ("postgres", "pgsql"), False, "PostgreSQL"),
    BackendSpec("mariadb", (), False, "MariaDB"),
    BackendSpec("mysql", (), False, "MySQL"),
    BackendSpec("mssql", ("sqlserver", "sql-server"), False, "Microsoft SQL Server"),
)


def normalize_backend_name(value: str) -> str:
    candidate = value.strip().lower()
    for backend in BACKENDS:
        if candidate == backend.name or candidate in backend.aliases:
            return backend.name
    known = ", ".join(backend.name for backend in BACKENDS)
    raise ValueError(f"unknown database backend {value!r}; known backends: {known}")


def backend_spec(name: str) -> BackendSpec:
    normalized = normalize_backend_name(name)
    return next(backend for backend in BACKENDS if backend.name == normalized)


@dataclass(frozen=True)
class DatabaseStatus:
    backend: str
    schema_version: int
    integrity: str
    location: str


class SQLiteDatabase:
    """Small synchronous SQLite lifecycle used only during startup and checks."""

    def __init__(self, config: DatabaseConfig, instance_name: str):
        if not config.path:
            raise DatabaseError("SQLite database.path was not resolved")
        self.path = Path(config.path)
        self.instance_name = instance_name
        self.busy_timeout_ms = int(config.busy_timeout_seconds * 1000)

    def connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
        else:
            connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    def initialize(self, *, create: bool = False) -> DatabaseStatus:
        if not self.path.exists() and not create:
            raise DatabaseError(
                f"database does not exist: {self.path}; initialize it explicitly"
            )
        existing_database = self.path.exists() and self.path.stat().st_size > 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            if existing_database:
                schema_table = connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'schema_migrations'
                    """
                ).fetchone()
                if not schema_table:
                    raise DatabaseError(
                        f"refusing to initialize an unknown existing database: {self.path}"
                    )
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS instance_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
                    VALUES (?, ?, ?)
                    """,
                    (1, "initial storage metadata", datetime.now(UTC).isoformat()),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO instance_metadata(key, value)
                    VALUES ('bot_name', ?)
                    """,
                    (self.instance_name,),
                )
            stored_name_row = connection.execute(
                "SELECT value FROM instance_metadata WHERE key = 'bot_name'"
            ).fetchone()
            stored_name = str(stored_name_row[0]) if stored_name_row else ""
            if stored_name != self.instance_name:
                raise DatabaseError(
                    f"database belongs to bot {stored_name!r}, not {self.instance_name!r}"
                )
            return self._status(connection)
        finally:
            connection.close()

    def check(self) -> DatabaseStatus:
        if not self.path.is_file():
            raise DatabaseError(f"database file does not exist: {self.path}")
        connection = self.connect(read_only=True)
        try:
            return self._status(connection)
        except sqlite3.DatabaseError as exc:
            raise DatabaseError(f"SQLite validation failed: {exc}") from exc
        finally:
            connection.close()

    def _status(self, connection: sqlite3.Connection) -> DatabaseStatus:
        integrity_row = connection.execute("PRAGMA quick_check").fetchone()
        integrity = str(integrity_row[0]) if integrity_row else "unknown"
        if integrity != "ok":
            raise DatabaseError(f"SQLite quick_check failed: {integrity}")
        try:
            row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        except sqlite3.DatabaseError as exc:
            raise DatabaseError("database has no NovariusIRC schema") from exc
        version = int(row[0] or 0)
        if version > SCHEMA_VERSION:
            raise DatabaseError(
                f"database schema {version} is newer than supported {SCHEMA_VERSION}"
            )
        if version < SCHEMA_VERSION:
            raise DatabaseError(
                f"database schema {version} requires migration to {SCHEMA_VERSION}"
            )
        return DatabaseStatus("sqlite", version, integrity, str(self.path))


def create_database(config: DatabaseConfig, instance_name: str) -> SQLiteDatabase:
    spec = backend_spec(config.backend)
    if spec.name == "sqlite":
        return SQLiteDatabase(config, instance_name)
    raise DatabaseBackendUnavailable(
        f"{spec.description} is a known backend but its adapter is not installed yet"
    )
