from __future__ import annotations

import pytest

from novariusirc.irc.ctcp import CTCPMessage, format_ctcp, parse_ctcp


def test_ctcp_parser_requires_one_complete_frame() -> None:
    assert parse_ctcp("\x01VERSION\x01") == CTCPMessage("VERSION")
    assert parse_ctcp("\x01PING opaque token\x01") == CTCPMessage(
        "PING", "opaque token"
    )
    assert parse_ctcp("normal text") is None
    assert parse_ctcp("\x01VERSION\x01trailing") is None
    assert parse_ctcp("\x01BAD\x01FRAME\x01") is None


def test_ctcp_formatter_sanitizes_parameters() -> None:
    assert format_ctcp("version", "one\ntwo") == "\x01VERSION one two\x01"
    with pytest.raises(ValueError, match="delimiter"):
        format_ctcp("VERSION", "bad\x01frame")
