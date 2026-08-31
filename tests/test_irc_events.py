from __future__ import annotations

from datetime import UTC, datetime

import pytest

from novariusirc.irc.events import IRCEnvelope
from novariusirc.irc.protocol import parse_message


def test_envelope_structures_source_and_event_time() -> None:
    message = parse_message(
        "@time=2026-08-31T12:00:00Z :Nick!user@host PRIVMSG #test :hello"
    )
    received = datetime(2026, 8, 31, 12, 0, 1, tzinfo=UTC)
    envelope = IRCEnvelope.from_message(message, received_at=received)

    assert envelope.source is not None
    assert envelope.source.name == "Nick"
    assert envelope.source.username == "user"
    assert envelope.source.hostname == "host"
    assert envelope.source.is_user
    assert envelope.event_time == datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def test_envelope_marks_invalid_server_time_and_requires_aware_receive_time() -> None:
    envelope = IRCEnvelope.from_message(parse_message("@time=bad PING :cookie"))
    assert envelope.invalid_server_time
    assert envelope.server_time is None

    with pytest.raises(ValueError, match="timezone-aware"):
        IRCEnvelope.from_message(
            parse_message("PING :cookie"),
            received_at=datetime(2026, 8, 31, tzinfo=UTC).replace(tzinfo=None),
        )
