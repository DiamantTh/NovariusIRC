from __future__ import annotations

from novariusirc.irc.protocol import parse_message
from novariusirc.irc.replies import ReplySeverity, parse_standard_reply


def test_standard_reply_is_structured_without_code_registry_assumptions() -> None:
    reply = parse_standard_reply(
        parse_message(":irc.example FAIL JOIN BANNED #room :Cannot join channel")
    )
    assert reply is not None
    assert reply.severity == ReplySeverity.FAILURE
    assert reply.command == "JOIN"
    assert reply.code == "BANNED"
    assert reply.context == ("#room",)
    assert reply.description == "Cannot join channel"


def test_non_standard_or_incomplete_reply_is_ignored() -> None:
    assert parse_standard_reply(parse_message("PING :cookie")) is None
    assert parse_standard_reply(parse_message("WARN COMMAND")) is None
