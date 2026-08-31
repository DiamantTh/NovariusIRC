from __future__ import annotations

import asyncio

import pytest

from novariusirc.irc.connection import (
    IncompleteIRCLine,
    IRCLineReader,
    OversizedIRCLine,
)


def test_line_reader_returns_complete_lines_and_eof() -> None:
    async def scenario() -> None:
        reader = asyncio.StreamReader()
        reader.feed_data(b"PING :cookie\r\n")
        reader.feed_eof()
        lines = IRCLineReader(reader, idle_timeout=1)
        assert await lines.read() == "PING :cookie"
        assert await lines.read() is None

    asyncio.run(scenario())


def test_line_reader_rejects_incomplete_and_oversized_lines() -> None:
    async def scenario() -> None:
        incomplete = asyncio.StreamReader()
        incomplete.feed_data(b"PING :cookie")
        incomplete.feed_eof()
        with pytest.raises(IncompleteIRCLine):
            await IRCLineReader(incomplete, idle_timeout=1).read()

        oversized = asyncio.StreamReader(limit=9000)
        oversized.feed_data(b"X" * 513 + b"\n")
        oversized.feed_eof()
        with pytest.raises(OversizedIRCLine) as error:
            await IRCLineReader(
                oversized, idle_timeout=1, maximum_bytes=512
            ).read()
        assert error.value.size == 514

    asyncio.run(scenario())
