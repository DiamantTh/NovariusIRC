"""Neutral metadata for incoming IRC messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .protocol import IRCMessage, parse_server_time
from .state import split_source


@dataclass(frozen=True)
class IRCSource:
    """Structured server or user prefix from an IRC message."""

    raw: str
    name: str
    username: str | None = None
    hostname: str | None = None

    @property
    def is_user(self) -> bool:
        return self.username is not None or self.hostname is not None

    @classmethod
    def parse(cls, prefix: str) -> IRCSource:
        name, username, hostname = split_source(prefix)
        return cls(prefix, name, username, hostname)


@dataclass(frozen=True)
class IRCEnvelope:
    """A parsed wire message with neutral source and time metadata."""

    message: IRCMessage
    source: IRCSource | None
    received_at: datetime
    server_time: datetime | None
    invalid_server_time: bool = False

    @property
    def event_time(self) -> datetime:
        return self.server_time or self.received_at

    @classmethod
    def from_message(
        cls, message: IRCMessage, *, received_at: datetime | None = None
    ) -> IRCEnvelope:
        received = received_at or datetime.now(UTC)
        if received.tzinfo is None:
            raise ValueError("IRC receive time must be timezone-aware")
        tagged_time = message.tags.get("time")
        server_time = parse_server_time(tagged_time)
        return cls(
            message=message,
            source=IRCSource.parse(message.prefix) if message.prefix else None,
            received_at=received,
            server_time=server_time,
            invalid_server_time="time" in message.tags and server_time is None,
        )
