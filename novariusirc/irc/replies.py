"""Structured IRCv3 standard replies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .protocol import IRCMessage


class ReplySeverity(StrEnum):
    FAILURE = "FAIL"
    WARNING = "WARN"
    NOTE = "NOTE"


@dataclass(frozen=True)
class StandardReply:
    severity: ReplySeverity
    command: str
    code: str
    context: tuple[str, ...]
    description: str


def parse_standard_reply(message: IRCMessage) -> StandardReply | None:
    """Parse FAIL/WARN/NOTE without assuming knowledge of reply codes."""
    try:
        severity = ReplySeverity(message.command)
    except ValueError:
        return None
    if len(message.params) < 2:
        return None
    command, code, *context = message.params
    return StandardReply(
        severity=severity,
        command=command.upper(),
        code=code,
        context=tuple(context),
        description=message.trailing or "",
    )
