"""Dedicated persistent storage for moderation history and evidence metadata."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    select,
)

server_metadata = MetaData()
server_actions = Table(
    "moderation_actions", server_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("action", String(16), nullable=False), Column("nick", String(128), nullable=False),
    Column("account", String(256)), Column("hostmask", Text), Column("channel", String(256), nullable=False),
    Column("reason", Text, nullable=False), Column("moderator", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False), Column("duration_seconds", Integer),
    Column("revoked_at", DateTime(timezone=True)),
)
Index(
    "ix_moderation_subject",
    server_actions.c.channel,
    server_actions.c.nick,
    server_actions.c.action,
    server_actions.c.revoked_at,
)
server_evidence = Table(
    "moderation_evidence", server_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("action_id", Integer, ForeignKey("moderation_actions.id"), nullable=False),
    Column("kind", String(64), nullable=False), Column("path", Text, nullable=False),
    Column("sha256", String(64)), Column("mime_type", String(128)), Column("size_bytes", Integer),
    Column("note", Text), Column("created_at", DateTime(timezone=True), nullable=False),
)


class ModerationStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS moderation_actions (
                    id INTEGER PRIMARY KEY,
                    action TEXT NOT NULL,
                    nick TEXT NOT NULL,
                    account TEXT,
                    hostmask TEXT,
                    channel TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    moderator TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    duration_seconds INTEGER,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_moderation_subject
                    ON moderation_actions(channel, nick, action, revoked_at);
                CREATE TABLE IF NOT EXISTS moderation_evidence (
                    id INTEGER PRIMARY KEY,
                    action_id INTEGER NOT NULL REFERENCES moderation_actions(id),
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    sha256 TEXT,
                    mime_type TEXT,
                    size_bytes INTEGER,
                    note TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def record_action(
        self,
        *,
        action: str,
        nick: str,
        account: str | None,
        hostmask: str | None,
        channel: str,
        reason: str,
        moderator: str,
        duration: int | None,
        created_at: datetime,
    ) -> int:
        with self._connect() as connection:
            result = connection.execute(
                """INSERT INTO moderation_actions
                (action, nick, account, hostmask, channel, reason, moderator, created_at, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (action, nick, account, hostmask, channel, reason, moderator,
                 created_at.astimezone(UTC).isoformat(), duration),
            )
            return int(result.lastrowid)


    def warning_count(self, nick: str, channel: str) -> int:
        with self._connect() as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM moderation_actions WHERE action = 'warn' "
                "AND nick = ? AND channel = ? AND revoked_at IS NULL", (nick, channel)
            ).fetchone()[0])

    def active_actions(self) -> list[sqlite3.Row]:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            return list(connection.execute(
                """SELECT * FROM moderation_actions WHERE revoked_at IS NULL
                AND action IN ('mute', 'ban')
                AND (duration_seconds IS NULL OR datetime(created_at, '+' || duration_seconds || ' seconds') > datetime(?))""",
                (now,),
            ))

    def revoke(self, nick: str, channel: str | None, action: str) -> None:
        statement = "UPDATE moderation_actions SET revoked_at = ? WHERE nick = ? AND action = ? AND revoked_at IS NULL"
        parameters: list[str] = [datetime.now(UTC).isoformat(), nick, action]
        if channel is not None:
            statement += " AND channel = ?"
            parameters.append(channel)
        with self._connect() as connection:
            connection.execute(statement, parameters)

    def add_evidence(
        self, action_id: int, *, kind: str, path: str, sha256: str | None = None,
        mime_type: str | None = None, size_bytes: int | None = None, note: str | None = None,
    ) -> int:
        with self._connect() as connection:
            result = connection.execute(
                """INSERT INTO moderation_evidence
                (action_id, kind, path, sha256, mime_type, size_bytes, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (action_id, kind, path, sha256, mime_type, size_bytes, note,
                 datetime.now(UTC).isoformat()),
            )
            return int(result.lastrowid)


class ServerModerationStore:
    """Portable SQLAlchemy moderation store for PostgreSQL, MariaDB, and peers."""

    def __init__(self, dsn: str):
        self.engine = create_engine(dsn, pool_pre_ping=True, pool_recycle=1800)
        server_metadata.create_all(self.engine)

    def record_action(self, **values) -> int:
        values["created_at"] = values["created_at"].astimezone(UTC)
        values["duration_seconds"] = values.pop("duration")
        with self.engine.begin() as connection:
            result = connection.execute(server_actions.insert().values(**values))
            return int(result.inserted_primary_key[0])

    def warning_count(self, nick: str, channel: str) -> int:
        with self.engine.connect() as connection:
            statement = select(func.count()).select_from(server_actions).where(
                server_actions.c.action == "warn", server_actions.c.nick == nick,
                server_actions.c.channel == channel, server_actions.c.revoked_at.is_(None)
            )
            return int(connection.execute(statement).scalar_one())

    def active_actions(self) -> list[dict]:
        from datetime import timedelta

        with self.engine.connect() as connection:
            rows = connection.execute(select(server_actions).where(
                server_actions.c.revoked_at.is_(None), server_actions.c.action.in_(("mute", "ban"))
            )).mappings()
            now = datetime.now(UTC)
            active: list[dict] = []
            for row in rows:
                action = dict(row)
                created_at = action["created_at"]
                # MariaDB and some PostgreSQL configurations return a naive
                # datetime even for timezone-aware columns.  DB timestamps are
                # written as UTC, so normalise the value before comparing it.
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                action["created_at"] = created_at
                if (
                    action["duration_seconds"] is None
                    or created_at + timedelta(seconds=action["duration_seconds"]) > now
                ):
                    active.append(action)
            return active

    def revoke(self, nick: str, channel: str | None, action: str) -> None:
        condition = [server_actions.c.nick == nick, server_actions.c.action == action,
                     server_actions.c.revoked_at.is_(None)]
        if channel is not None:
            condition.append(server_actions.c.channel == channel)
        with self.engine.begin() as connection:
            connection.execute(server_actions.update().where(*condition).values(revoked_at=datetime.now(UTC)))

    def add_evidence(self, action_id: int, **values) -> int:
        values.update(action_id=action_id, created_at=datetime.now(UTC))
        with self.engine.begin() as connection:
            result = connection.execute(server_evidence.insert().values(**values))
            return int(result.inserted_primary_key[0])
