from __future__ import annotations

import pytest

from novariusirc.irc.protocol import (
    IRCFeatures,
    irc_casefold,
    parse_message,
    parse_server_time,
)


def test_message_tags_are_parsed_and_unescaped() -> None:
    message = parse_message(
        r"@account=alice;server-time=2026-08-29T12:00:00Z;example=a\sb\:c\\d "
        ":Nick!user@host PRIVMSG #Test :hello world"
    )

    assert message.command == "PRIVMSG"
    assert message.prefix == "Nick!user@host"
    assert message.params == ("#Test",)
    assert message.trailing == "hello world"
    assert message.tags["account"] == "alice"
    assert message.tags["example"] == "a b;c\\d"


def test_tag_keys_are_opaque_duplicates_use_last_and_empty_is_distinct() -> None:
    message = parse_message(
        "@future$key=kept;Duplicate=first;Duplicate=last;empty= PING :cookie"
    )

    assert message.tags["future$key"] == "kept"
    assert message.tags["Duplicate"] == "last"
    assert message.tags["empty"] == ""

    valueless = parse_message("@empty PING :cookie")
    assert valueless.tags["empty"] is None


def test_tagged_ping_is_a_normal_parsed_message() -> None:
    message = parse_message("@time=now PING :keepalive-cookie")
    assert message.command == "PING"
    assert message.trailing == "keepalive-cookie"


@pytest.mark.parametrize(
    ("mapping", "left", "right", "equal"),
    [
        ("ascii", "Nick[", "nick{", False),
        ("rfc1459-strict", "Nick[", "nick{", True),
        ("rfc1459-strict", "Nick^", "nick~", False),
        ("rfc1459", "Nick^", "nick~", True),
    ],
)
def test_irc_casemapping(mapping: str, left: str, right: str, equal: bool) -> None:
    assert (irc_casefold(left, mapping) == irc_casefold(right, mapping)) is equal


def test_isupport_updates_casemapping_and_chantypes() -> None:
    features = IRCFeatures()
    features.update(["Bot", "CASEMAPPING=ascii", "CHANTYPES=#", "NETWORK=ExampleNet"])

    assert features.casemapping == "ascii"
    assert features.is_channel("#channel")
    assert not features.is_channel("&local")
    assert features.network == "ExampleNet"


def test_malformed_prefix_is_rejected_without_index_error() -> None:
    with pytest.raises(ValueError, match="source prefix"):
        parse_message(":server-only")


def test_parser_accepts_more_than_fifteen_parameters() -> None:
    message = parse_message("COMMAND " + " ".join(f"p{index}" for index in range(20)))
    assert len(message.params) == 20


@pytest.mark.parametrize("command", ["!INVALID", "12", "1234", "CMD_1"])
def test_parser_rejects_invalid_command_syntax(command: str) -> None:
    with pytest.raises(ValueError, match="Invalid IRC command"):
        parse_message(f"{command} value")


def test_message_body_limit_is_enforced_separately_from_tags() -> None:
    parse_message("@label=ok PRIVMSG #test :" + "x" * 495)
    with pytest.raises(ValueError, match="body exceeds"):
        parse_message("@label=ok PRIVMSG #test :" + "x" * 496)


def test_server_time_supports_fractional_and_leap_seconds() -> None:
    regular = parse_server_time("2026-08-29T12:34:56.123Z")
    leap = parse_server_time("2016-12-31T23:59:60.500Z")

    assert regular is not None
    assert regular.isoformat() == "2026-08-29T12:34:56.123000+00:00"
    assert leap is not None
    assert leap.isoformat() == "2017-01-01T00:00:00.500000+00:00"
    assert parse_server_time("not-a-time") is None
    assert parse_server_time("2026-08-29T12:34:61.000Z") is None
    assert parse_server_time("2026-08-29T12:34:56.000+02:00") is None
