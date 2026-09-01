from __future__ import annotations

import json
import logging
import sqlite3
import tarfile
from pathlib import Path

import pytest

from novariusirc.__main__ import check_config
from novariusirc.core.auth import AuthManager
from novariusirc.core.backups import BackupManager
from novariusirc.core.config import (
    BackupConfig,
    Config,
    DatabaseConfig,
    safe_filename_component,
)
from novariusirc.core.database import (
    DatabaseBackendUnavailable,
    DatabaseError,
    SQLiteDatabase,
    StoredFeedState,
    create_database,
    normalize_backend_name,
)


def write_config(path: Path, database: str = "") -> Config:
    path.write_text(
        f"""
[bot]
name = "My Bot[EU]"

[network]
server = "irc.example.test"
nick = "RuntimeBot"
user = "bot"
realname = "Bot"

[database]
enabled = true
backend = "sqlite"
{database}

[owner_bootstrap]
hostmask = "owner!*@trusted.example"
""".strip(),
        encoding="utf-8",
    )
    return Config.load(path)


def test_database_backend_names_are_normalized() -> None:
    assert normalize_backend_name("sqlite3") == "sqlite"
    assert normalize_backend_name("POSTGRES") == "postgresql"
    assert normalize_backend_name("sql-server") == "mssql"
    with pytest.raises(ValueError, match="known backends"):
        normalize_backend_name("unknown")


def test_stable_bot_name_controls_default_database_filename(tmp_path: Path) -> None:
    config = write_config(tmp_path / "config.toml")

    assert config.bot.name == "My Bot[EU]"
    assert config.database.path == str(tmp_path / "data" / "My_Bot_EU.sqlite3")
    assert safe_filename_component(config.bot.name) == "My_Bot_EU"


def test_network_nick_is_the_default_bot_name(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[bot]

[network]
server = "irc.example.test"
nick = "RuntimeBot"
user = "bot"
realname = "Bot"
""".strip(),
        encoding="utf-8",
    )

    assert Config.load(config_file).bot.name == "RuntimeBot"


def test_sqlite_database_requires_explicit_initialization(tmp_path: Path) -> None:
    config = write_config(tmp_path / "config.toml")
    database = create_database(config.database, config.bot.name or "")

    with pytest.raises(DatabaseError, match="does not exist"):
        database.initialize()

    status = database.initialize(create=True)
    assert status.integrity == "ok"
    assert status.schema_version == "0002_persistent_core_state"
    assert database.check() == status


def test_sqlite_database_records_and_checks_instance_name(tmp_path: Path) -> None:
    path = tmp_path / "bot.sqlite3"
    database = SQLiteDatabase(DatabaseConfig(path=str(path)), "FirstBot")
    database.initialize(create=True)

    other = SQLiteDatabase(DatabaseConfig(path=str(path)), "OtherBot")
    with pytest.raises(DatabaseError, match="belongs to bot"):
        other.initialize()


def test_sqlite_refuses_unknown_existing_database(tmp_path: Path) -> None:
    path = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")

    database = SQLiteDatabase(DatabaseConfig(path=str(path)), "TestBot")
    with pytest.raises(DatabaseError, match="unknown existing database"):
        database.initialize(create=True)


def test_sqlite_migrates_the_legacy_metadata_database(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE instance_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES (1, 'initial storage metadata', 'now')"
        )
        connection.execute(
            "INSERT INTO instance_metadata VALUES ('bot_name', 'TestBot')"
        )

    status = SQLiteDatabase(DatabaseConfig(path=str(path)), "TestBot").initialize(
        create=True
    )

    assert status.schema_version == "0002_persistent_core_state"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0002_persistent_core_state",
        )


def test_database_upgrade_from_previous_alembic_revision_preserves_metadata(
    tmp_path: Path,
) -> None:
    database = SQLiteDatabase(DatabaseConfig(path=str(tmp_path / "bot.sqlite3")), "TestBot")
    database.initialize(create=True)
    with sqlite3.connect(database.path) as connection:
        connection.execute("DROP TABLE feed_states")
        connection.execute("DROP TABLE role_bindings")
        connection.execute("DROP TABLE roles")
        connection.execute("UPDATE alembic_version SET version_num = '0001_storage_metadata'")

    with pytest.raises(DatabaseError, match="requires migration"):
        database.check()
    status = database.initialize(create=True)

    assert status.schema_version == "0002_persistent_core_state"
    assert database.check() == status


def test_sqlite_persists_feed_state_and_exposes_empty_role_bindings(
    tmp_path: Path,
) -> None:
    database = SQLiteDatabase(DatabaseConfig(path=str(tmp_path / "bot.sqlite3")), "TestBot")
    database.initialize(create=True)

    assert database.list_role_bindings() == []
    database.save_feed_state(
        "https://example.test/feed.xml",
        StoredFeedState("etag", "yesterday", ["first", "first", "second"]),
    )

    assert database.load_feed_state("https://example.test/feed.xml") == StoredFeedState(
        "etag", "yesterday", ["first", "second"]
    )


def test_owner_bootstrap_runs_once_and_role_bindings_authorize_identities(
    tmp_path: Path,
) -> None:
    database = SQLiteDatabase(DatabaseConfig(path=str(tmp_path / "bot.sqlite3")), "TestBot")
    database.initialize(create=True)

    seeded = database.bootstrap_owner_bindings(
        [("hostmask", "Owner!*@trusted.example"), ("account", "owner-account")]
    )
    assert [binding.role_name for binding in seeded] == ["owner", "owner"]
    assert database.bootstrap_owner_bindings([("hostmask", "Other!*@example")]) == []
    database.add_role_binding("admin", "certfp", "AB:CD")

    config = Config.model_validate(
        {
            "bot": {},
            "network": {
                "server": "irc.example.test",
                "nick": "bot",
                "user": "bot",
                "realname": "Bot",
            },
        }
    )
    auth = AuthManager(
        config.auth,
        config.roles,
        logging.getLogger("test.database"),
        persistent_bindings=database.list_role_bindings(),
    )

    assert "owner" in auth.roles_for_identity("Owner", "Owner!u@trusted.example")
    assert "owner" in auth.roles_for_identity(
        "untrusted", "untrusted!u@host", account="owner-account"
    )
    assert "admin" in auth.roles_for_identity(
        "untrusted", "untrusted!u@host", certfp="ab:cd"
    )
    for binding in database.list_role_bindings():
        database.remove_role_binding(binding.id)
    assert database.bootstrap_owner_bindings([("hostmask", "Other!*@example")]) == []


def test_backup_uses_sqlite_snapshot_and_records_data_files(tmp_path: Path) -> None:
    database = SQLiteDatabase(DatabaseConfig(path=str(tmp_path / "data" / "bot.sqlite3")), "TestBot")
    database.initialize(create=True)
    database.bootstrap_owner_bindings([("hostmask", "owner!*@trusted.example")])
    data_file = tmp_path / "data" / "notes.txt"
    data_file.write_text("keep this", encoding="utf-8")
    manager = BackupManager(
        BackupConfig(enabled=True, directory=str(tmp_path / "backups")),
        database,
        "TestBot",
        tmp_path / "data",
    )

    result = manager.create()

    assert result.path.name.startswith("TestBot_")
    assert result.path.suffix == ".tar"
    assert manager.list() == [result.path]
    with tarfile.open(result.path) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        assert manifest["bot_name"] == "TestBot"
        assert {item["path"] for item in manifest["files"]} == {
            "database.sqlite3",
            "data/notes.txt",
        }
        assert archive.extractfile("database.sqlite3") is not None

    database.add_role_binding("admin", "account", "new-admin")
    manager.restore(result.path, replace=True, restore_data=True)
    assert not any(
        binding.binding_value == "new-admin" for binding in database.list_role_bindings()
    )
    assert data_file.read_text(encoding="utf-8") == "keep this"


def test_known_server_backend_fails_with_actionable_error() -> None:
    config = DatabaseConfig(enabled=True, backend="postgresql", dsn="postgresql://db")
    with pytest.raises(DatabaseBackendUnavailable, match="known backend"):
        create_database(config, "TestBot")


def test_check_config_reports_uninitialized_database(tmp_path: Path) -> None:
    config = write_config(tmp_path / "config.toml")
    assert any("--init-database" in error for error in check_config(config))

    create_database(config.database, config.bot.name or "").initialize(create=True)
    assert not [error for error in check_config(config) if "database" in error.lower()]
