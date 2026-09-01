"""Database backend registry and Alembic-backed storage lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from .database_schema import instance_metadata

if TYPE_CHECKING:
    from .config import DatabaseConfig


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
    schema_version: str
    integrity: str
    location: str


class SQLiteDatabase:
    """SQLite lifecycle using SQLAlchemy Core and packaged Alembic revisions."""

    def __init__(self, config: DatabaseConfig, instance_name: str):
        if not config.path:
            raise DatabaseError("SQLite database.path was not resolved")
        self.path = Path(config.path)
        self.instance_name = instance_name
        self.busy_timeout_ms = int(config.busy_timeout_seconds * 1000)
        self.connect_timeout_seconds = config.connect_timeout_seconds

    def _url(self, *, read_only: bool = False) -> str:
        path = self.path.resolve().as_posix()
        if read_only:
            return f"sqlite+pysqlite:///file:{path}?mode=ro&uri=true"
        return f"sqlite+pysqlite:///{path}"

    def _engine(self, *, read_only: bool = False) -> Engine:
        engine = create_engine(
            self._url(read_only=read_only),
            connect_args={"timeout": self.connect_timeout_seconds},
        )

        @event.listens_for(engine, "connect")
        def configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            cursor.close()

        return engine

    @staticmethod
    def _migration_config(connection: Connection) -> AlembicConfig:
        migrations_path = Path(__file__).parents[1] / "migrations"
        config = AlembicConfig()
        config.set_main_option("script_location", str(migrations_path))
        config.attributes["connection"] = connection
        return config

    def _is_known_database(self, connection: Connection) -> bool:
        tables = set(inspect(connection).get_table_names())
        return bool(
            {"alembic_version", "instance_metadata", "schema_migrations"} & tables
        )

    def _prepare_sqlite(self, connection: Connection) -> None:
        connection.execute(text("PRAGMA journal_mode = WAL"))
        connection.execute(text("PRAGMA synchronous = FULL"))

    def _run_migrations(self, connection: Connection) -> None:
        command.upgrade(self._migration_config(connection), "head")

    def initialize(self, *, create: bool = False) -> DatabaseStatus:
        if not self.path.exists() and not create:
            raise DatabaseError(
                f"database does not exist: {self.path}; initialize it explicitly"
            )
        existing_database = self.path.exists() and self.path.stat().st_size > 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        engine = self._engine()
        try:
            with engine.connect() as connection:
                if existing_database and not self._is_known_database(connection):
                    raise DatabaseError(
                        f"refusing to initialize an unknown existing database: {self.path}"
                    )
                self._prepare_sqlite(connection)
                self._run_migrations(connection)
                connection.commit()
                with connection.begin():
                    stored_name = connection.execute(
                        select(instance_metadata.c.value).where(
                            instance_metadata.c.key == "bot_name"
                        )
                    ).scalar_one_or_none()
                    if stored_name is None:
                        connection.execute(
                            instance_metadata.insert().values(
                                key="bot_name", value=self.instance_name
                            )
                        )
                    elif stored_name != self.instance_name:
                        raise DatabaseError(
                            "database belongs to bot "
                            f"{stored_name!r}, not {self.instance_name!r}"
                        )
                return self._status(connection)
        except SQLAlchemyError as exc:
            raise DatabaseError(f"SQLite initialization failed: {exc}") from exc
        finally:
            engine.dispose()

    def check(self) -> DatabaseStatus:
        if not self.path.is_file():
            raise DatabaseError(f"database file does not exist: {self.path}")
        engine = self._engine(read_only=True)
        try:
            with engine.connect() as connection:
                return self._status(connection)
        except SQLAlchemyError as exc:
            raise DatabaseError(f"SQLite validation failed: {exc}") from exc
        finally:
            engine.dispose()

    def _status(self, connection: Connection) -> DatabaseStatus:
        integrity = str(connection.execute(text("PRAGMA quick_check")).scalar_one())
        if integrity != "ok":
            raise DatabaseError(f"SQLite quick_check failed: {integrity}")
        tables = set(inspect(connection).get_table_names())
        if "alembic_version" not in tables or "instance_metadata" not in tables:
            raise DatabaseError("database has no current NovariusIRC schema")
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
        head = ScriptDirectory.from_config(
            self._migration_config(connection)
        ).get_current_head()
        if revision != head:
            raise DatabaseError(
                f"database schema {revision or 'none'} requires migration to {head}"
            )
        stored_name = connection.execute(
            select(instance_metadata.c.value).where(instance_metadata.c.key == "bot_name")
        ).scalar_one_or_none()
        if stored_name != self.instance_name:
            raise DatabaseError(
                f"database belongs to bot {stored_name!r}, not {self.instance_name!r}"
            )
        return DatabaseStatus("sqlite", str(revision), integrity, str(self.path))


def create_database(config: DatabaseConfig, instance_name: str) -> SQLiteDatabase:
    spec = backend_spec(config.backend)
    if spec.name == "sqlite":
        return SQLiteDatabase(config, instance_name)
    raise DatabaseBackendUnavailable(
        f"{spec.description} is a known backend but its SQLAlchemy adapter is not installed yet"
    )
