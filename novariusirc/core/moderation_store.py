"""Small, dedicated SQLite store for moderation history and evidence metadata."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


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
