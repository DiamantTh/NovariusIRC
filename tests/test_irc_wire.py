from __future__ import annotations

import pytest

from novariusirc.irc.wire import (
    format_join,
    format_nick,
    format_text_command,
    format_user,
    truncate_utf8,
    validate_raw_line,
)


def test_text_commands_are_sanitized_and_utf8_safe() -> None:
    line = format_text_command("PRIVMSG", "#safe", "first\nsecond " + "ä" * 400)
    assert line.startswith("PRIVMSG #safe :first second ")
    assert len(line.encode()) <= 510
    line.encode().decode("utf-8")


def test_wire_builders_reject_command_injection() -> None:
    with pytest.raises(ValueError, match="CR, LF, or NUL"):
        validate_raw_line("PING\r\nOPER attacker")
    with pytest.raises(ValueError, match="Invalid IRC target"):
        format_text_command("NOTICE", "Nick OPER attacker", "hello")
    with pytest.raises(ValueError, match="Invalid IRC channel"):
        format_join("#safe,#other")


def test_wire_helpers_reject_unsupported_commands_and_preserve_codepoints() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        format_text_command("TAGMSG", "#safe", "hello")
    assert truncate_utf8("äö", 3) == "ä"


def test_registration_lines_are_framed_safely() -> None:
    assert format_nick("NovariusBot") == "NICK NovariusBot"
    assert format_user("novarius", "Novarius IRC Bot") == (
        "USER novarius 0 * :Novarius IRC Bot"
    )
    with pytest.raises(ValueError, match="nickname"):
        format_nick("bad nick")
    with pytest.raises(ValueError, match="username"):
        format_user(":bad", "Bot")
    with pytest.raises(ValueError, match="real name"):
        format_user("bot", "bad\nOPER")
