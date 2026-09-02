"""Database backend registry and Alembic-backed storage lifecycle."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from .database_schema import feed_states, instance_metadata, role_bindings

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
ROLE_NAMES = frozenset(("user", "admin", "owner"))
BINDING_TYPES = frozenset(("hostmask", "account", "certfp"))
OWNER_BOOTSTRAP_METADATA_KEY = "owner_bootstrap_completed_at"


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


@dataclass(frozen=True)
class DatabaseUpgradeResult:
    """Outcome of a safe, file-based SQLite schema upgrade."""

    status: DatabaseStatus
    previous_copy: Path | None
    previous_sha256: str | None
    upgraded_sha256: str | None


@dataclass(frozen=True)
class RoleBinding:
    """One persistent role assignment to an IRC identity attribute."""

    id: int
    role_name: str
    binding_type: str
    binding_value: str


@dataclass(frozen=True)
class StoredFeedState:
    """Serialized feed polling state, independent from the feed module."""

    etag: str | None
    last_modified: str | None
    seen_ids: list[str]


class DatabaseBackend(Protocol):
    """Backend-facing storage contract used by core services.

    Core services never select a SQL dialect or access database files.  A
    backend owns its engine, integrity checks, backup representation, and
    backend-specific restore mechanics.
    """

    backend_name: str
    backup_snapshot_name: str

    def initialize(self, *, create: bool = False) -> DatabaseStatus: ...

    def check(self) -> DatabaseStatus: ...

    def upgrade_safely(self) -> DatabaseUpgradeResult: ...

    def create_backup_snapshot(self, destination: Path) -> None: ...

    def validate_backup_snapshot(self, snapshot: Path) -> None: ...

    def restore_backup_snapshot(self, snapshot: Path, *, replace: bool) -> None: ...

    def backup_excluded_data_paths(self) -> set[Path]: ...

    def list_role_bindings(self) -> list[RoleBinding]: ...

    def add_role_binding(
        self, role_name: str, binding_type: str, binding_value: str
    ) -> RoleBinding: ...

    def remove_role_binding(self, binding_id: int) -> bool: ...

    def bootstrap_owner_bindings(
        self, bindings: list[tuple[str, str]]
    ) -> list[RoleBinding]: ...

    def load_feed_state(self, feed_url: str) -> StoredFeedState | None: ...

    def save_feed_state(self, feed_url: str, state: StoredFeedState) -> None: ...


class SQLiteDatabase:
    """SQLite lifecycle using SQLAlchemy Core and packaged Alembic revisions."""

    backend_name = "sqlite"
    backup_snapshot_name = "database.sqlite3"

    def __init__(self, config: DatabaseConfig, instance_name: str):
        if not config.path:
            raise DatabaseError("SQLite database.path was not resolved")
        self.config = config
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

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _migration_required(self, connection: Connection) -> bool:
        tables = set(inspect(connection).get_table_names())
        if "alembic_version" not in tables:
            return True
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
        head = ScriptDirectory.from_config(
            self._migration_config(connection)
        ).get_current_head()
        return revision != head

    def _initialize_in_place(self, *, create: bool = False) -> DatabaseStatus:
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

    def initialize(self, *, create: bool = False) -> DatabaseStatus:
        """Create a new database or safely upgrade a known existing database."""
        if not self.path.exists():
            return self._initialize_in_place(create=create)
        if not self.path.is_file():
            raise DatabaseError(f"database path is not a file: {self.path}")
        if self.path.stat().st_size == 0:
            return self._initialize_in_place(create=create)
        engine = self._engine(read_only=True)
        try:
            with engine.connect() as connection:
                if not self._is_known_database(connection):
                    raise DatabaseError(
                        f"refusing to initialize an unknown existing database: {self.path}"
                    )
                migration_required = self._migration_required(connection)
        except SQLAlchemyError as exc:
            raise DatabaseError(f"SQLite migration check failed: {exc}") from exc
        finally:
            engine.dispose()
        if not migration_required:
            return self.check()
        return self.upgrade_safely().status

    def upgrade_safely(self) -> DatabaseUpgradeResult:
        """Upgrade a known SQLite database on a copy and atomically replace it.

        The old live file is never modified.  A timestamped pre-upgrade copy is
        retained beside it, so a failed migration leaves the original untouched.
        The bot must be stopped: SQLite can snapshot concurrent writes safely,
        but those writes would not be present in the candidate being swapped in.
        """
        if not self.path.is_file():
            raise DatabaseError(f"database file does not exist: {self.path}")
        engine = self._engine(read_only=True)
        try:
            with engine.connect() as connection:
                if not self._is_known_database(connection):
                    raise DatabaseError(
                        f"refusing to migrate an unknown database: {self.path}"
                    )
                if not self._migration_required(connection):
                    return DatabaseUpgradeResult(self.check(), None, None, None)
        except SQLAlchemyError as exc:
            raise DatabaseError(f"SQLite migration check failed: {exc}") from exc
        finally:
            engine.dispose()

        source_size = sum(
            candidate.stat().st_size
            for candidate in (
                self.path,
                Path(f"{self.path}-wal"),
                Path(f"{self.path}-shm"),
            )
            if candidate.is_file()
        )
        available = shutil.disk_usage(self.path.parent).free
        required = max(source_size * 2, 1)
        if available < required:
            raise DatabaseError(
                f"insufficient free space for safe migration: need {required} bytes, "
                f"have {available}"
            )

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        previous_copy = self.path.with_name(
            f"{self.path.stem}.pre-migration-{timestamp}{self.path.suffix}"
        )
        candidate = self.path.with_name(
            f".{self.path.stem}.migration-{timestamp}{self.path.suffix}"
        )
        prepared = self.path.with_name(
            f".{self.path.stem}.migration-ready-{timestamp}{self.path.suffix}"
        )
        if previous_copy.exists() or candidate.exists() or prepared.exists():
            raise DatabaseError("migration staging path already exists; retry after inspection")
        self.create_backup_snapshot(previous_copy)
        previous_sha256 = self._sha256(previous_copy)
        try:
            self.create_backup_snapshot(candidate)
            candidate_config = self.config.model_copy(update={"path": str(candidate)})
            candidate_database = SQLiteDatabase(candidate_config, self.instance_name)
            candidate_database._initialize_in_place(create=True)
            # Snapshot once more after migration so no candidate WAL file is
            # needed after the final atomic rename.
            candidate_database.create_backup_snapshot(prepared)
            candidate_database.validate_backup_snapshot(prepared)
            prepared.chmod(self.path.stat().st_mode)
            upgraded_sha256 = self._sha256(prepared)
            prepared.replace(self.path)
            for suffix in ("-wal", "-shm"):
                Path(f"{self.path}{suffix}").unlink(missing_ok=True)
                Path(f"{candidate}{suffix}").unlink(missing_ok=True)
            candidate.unlink(missing_ok=True)
            return DatabaseUpgradeResult(
                self.check(), previous_copy, previous_sha256, upgraded_sha256
            )
        except Exception:
            for path in (candidate, prepared):
                path.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                Path(f"{candidate}{suffix}").unlink(missing_ok=True)
            raise

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

    def create_backup_snapshot(self, destination: Path) -> None:
        """Create a consistent SQLite snapshot without exposing SQLite to callers."""
        try:
            with sqlite3.connect(self.path) as source, sqlite3.connect(
                destination
            ) as target:
                source.backup(target)
        except sqlite3.Error as exc:
            raise DatabaseError(f"SQLite backup failed: {exc}") from exc

    def validate_backup_snapshot(self, snapshot: Path) -> None:
        """Validate a SQLite snapshot before it can replace live state."""
        try:
            with sqlite3.connect(snapshot) as connection:
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise DatabaseError("backup database integrity check failed")
        except sqlite3.Error as exc:
            raise DatabaseError(f"backup database is invalid: {exc}") from exc

    def restore_backup_snapshot(self, snapshot: Path, *, replace: bool) -> None:
        """Replace the database from a verified SQLite snapshot when allowed."""
        if self.path.exists() and not replace:
            raise DatabaseError("database exists; use --replace-database to restore")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_database = self.path.with_suffix(".restore.tmp")
        shutil.copy2(snapshot, temporary_database)
        temporary_database.replace(self.path)
        for suffix in ("-wal", "-shm"):
            Path(f"{self.path}{suffix}").unlink(missing_ok=True)

    def backup_excluded_data_paths(self) -> set[Path]:
        """Return live files that must not be recursively copied into a backup."""
        database_path = self.path.resolve()
        return {
            database_path,
            Path(f"{database_path}-wal"),
            Path(f"{database_path}-shm"),
        }

    def list_role_bindings(self) -> list[RoleBinding]:
        """Return the role assignments for the in-memory authorization cache."""
        engine = self._engine(read_only=True)
        try:
            with engine.connect() as connection:
                rows = connection.execute(
                    select(
                        role_bindings.c.id,
                        role_bindings.c.role_name,
                        role_bindings.c.binding_type,
                        role_bindings.c.binding_value,
                    ).order_by(role_bindings.c.id)
                )
                return [
                    RoleBinding(
                        id=int(row.id),
                        role_name=str(row.role_name),
                        binding_type=str(row.binding_type),
                        binding_value=str(row.binding_value),
                    )
                    for row in rows
                ]
        except SQLAlchemyError as exc:
            raise DatabaseError(f"could not read role bindings: {exc}") from exc
        finally:
            engine.dispose()

    @staticmethod
    def _validate_role_binding(
        role_name: str, binding_type: str, binding_value: str
    ) -> tuple[str, str, str]:
        role_name = role_name.strip().lower()
        binding_type = binding_type.strip().lower()
        binding_value = binding_value.strip()
        if role_name not in ROLE_NAMES:
            raise DatabaseError(f"unknown role: {role_name!r}")
        if binding_type not in BINDING_TYPES:
            raise DatabaseError(f"unknown role binding type: {binding_type!r}")
        if not binding_value or any(character in binding_value for character in "\r\n\0"):
            raise DatabaseError("role binding value must be non-empty plain text")
        if binding_type == "account" and any(character.isspace() for character in binding_value):
            raise DatabaseError("IRC account bindings must not contain whitespace")
        if binding_type == "certfp":
            normalized = binding_value.replace(":", "")
            if not re.fullmatch(r"[0-9a-fA-F]+", normalized):
                raise DatabaseError("CertFP bindings must be hexadecimal fingerprints")
            binding_value = normalized.lower()
        return role_name, binding_type, binding_value

    def add_role_binding(
        self, role_name: str, binding_type: str, binding_value: str
    ) -> RoleBinding:
        """Create a role binding and return its stable numeric ID."""
        role_name, binding_type, binding_value = self._validate_role_binding(
            role_name, binding_type, binding_value
        )
        engine = self._engine()
        try:
            with engine.begin() as connection:
                result = connection.execute(
                    role_bindings.insert().values(
                        role_name=role_name,
                        binding_type=binding_type,
                        binding_value=binding_value,
                        created_at=datetime.now(UTC),
                    )
                )
                binding_id = result.inserted_primary_key[0]
                if binding_id is None:
                    raise DatabaseError("database did not return the role binding ID")
                return RoleBinding(
                    id=int(binding_id),
                    role_name=role_name,
                    binding_type=binding_type,
                    binding_value=binding_value,
                )
        except SQLAlchemyError as exc:
            raise DatabaseError(f"could not add role binding: {exc}") from exc
        finally:
            engine.dispose()

    def remove_role_binding(self, binding_id: int) -> bool:
        """Remove one role binding by ID; the owner safety check is caller-owned."""
        if binding_id < 1:
            raise DatabaseError("role binding ID must be positive")
        engine = self._engine()
        try:
            with engine.begin() as connection:
                result = connection.execute(
                    role_bindings.delete().where(role_bindings.c.id == binding_id)
                )
                return result.rowcount == 1
        except SQLAlchemyError as exc:
            raise DatabaseError(f"could not remove role binding: {exc}") from exc
        finally:
            engine.dispose()

    def bootstrap_owner_bindings(
        self, bindings: list[tuple[str, str]]
    ) -> list[RoleBinding]:
        """Seed owners once; later starts never reapply environment input."""
        normalized = [
            self._validate_role_binding("owner", binding_type, binding_value)
            for binding_type, binding_value in bindings
        ]
        if not normalized:
            return []
        deduplicated = list(dict.fromkeys((kind, value) for _, kind, value in normalized))
        engine = self._engine()
        try:
            with engine.begin() as connection:
                completed = connection.execute(
                    select(instance_metadata.c.value).where(
                        instance_metadata.c.key == OWNER_BOOTSTRAP_METADATA_KEY
                    )
                ).scalar_one_or_none()
                if completed is not None:
                    return []
                existing = connection.execute(
                    select(role_bindings.c.id).where(role_bindings.c.role_name == "owner")
                ).first()
                if existing is not None:
                    connection.execute(
                        instance_metadata.insert().values(
                            key=OWNER_BOOTSTRAP_METADATA_KEY,
                            value=datetime.now(UTC).isoformat(),
                        )
                    )
                    return []
                created: list[RoleBinding] = []
                for binding_type, binding_value in deduplicated:
                    result = connection.execute(
                        role_bindings.insert().values(
                            role_name="owner",
                            binding_type=binding_type,
                            binding_value=binding_value,
                            created_at=datetime.now(UTC),
                        )
                    )
                    binding_id = result.inserted_primary_key[0]
                    if binding_id is None:
                        raise DatabaseError("database did not return the role binding ID")
                    created.append(
                        RoleBinding(
                            id=int(binding_id),
                            role_name="owner",
                            binding_type=binding_type,
                            binding_value=binding_value,
                        )
                    )
                connection.execute(
                    instance_metadata.insert().values(
                        key=OWNER_BOOTSTRAP_METADATA_KEY,
                        value=datetime.now(UTC).isoformat(),
                    )
                )
                return created
        except SQLAlchemyError as exc:
            raise DatabaseError(f"could not bootstrap owner bindings: {exc}") from exc
        finally:
            engine.dispose()

    def load_feed_state(self, feed_url: str) -> StoredFeedState | None:
        """Read feed state without exposing SQL details to the feed module."""
        engine = self._engine(read_only=True)
        try:
            with engine.connect() as connection:
                row = connection.execute(
                    select(
                        feed_states.c.etag,
                        feed_states.c.last_modified,
                        feed_states.c.seen_ids,
                    ).where(feed_states.c.feed_url == feed_url)
                ).one_or_none()
                if row is None:
                    return None
                try:
                    seen_ids = json.loads(row.seen_ids)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise DatabaseError(
                        f"invalid stored feed state for {feed_url!r}"
                    ) from exc
                if not isinstance(seen_ids, list) or not all(
                    isinstance(item, str) for item in seen_ids
                ):
                    raise DatabaseError(f"invalid stored feed IDs for {feed_url!r}")
                return StoredFeedState(
                    etag=row.etag,
                    last_modified=row.last_modified,
                    seen_ids=list(dict.fromkeys(seen_ids)),
                )
        except SQLAlchemyError as exc:
            raise DatabaseError(f"could not read feed state: {exc}") from exc
        finally:
            engine.dispose()

    def save_feed_state(self, feed_url: str, state: StoredFeedState) -> None:
        """Atomically replace the state stored for one feed URL."""
        payload = json.dumps(list(dict.fromkeys(state.seen_ids)), ensure_ascii=False)
        now = datetime.now(UTC)
        engine = self._engine()
        try:
            with engine.begin() as connection:
                result = connection.execute(
                    feed_states.update()
                    .where(feed_states.c.feed_url == feed_url)
                    .values(
                        etag=state.etag,
                        last_modified=state.last_modified,
                        seen_ids=payload,
                        updated_at=now,
                    )
                )
                if result.rowcount == 0:
                    connection.execute(
                        feed_states.insert().values(
                            feed_url=feed_url,
                            etag=state.etag,
                            last_modified=state.last_modified,
                            seen_ids=payload,
                            updated_at=now,
                        )
                    )
        except SQLAlchemyError as exc:
            raise DatabaseError(f"could not save feed state: {exc}") from exc
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


def create_database(config: DatabaseConfig, instance_name: str) -> DatabaseBackend:
    spec = backend_spec(config.backend)
    if spec.name == "sqlite":
        return SQLiteDatabase(config, instance_name)
    raise DatabaseBackendUnavailable(
        f"{spec.description} is a known backend but its SQLAlchemy adapter is not installed yet"
    )
