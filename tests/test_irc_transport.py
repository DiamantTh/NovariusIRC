from __future__ import annotations

import asyncio

import pytest

from novariusirc.irc.transport import RateLimitedSender


def test_sender_queues_normal_lines_and_bypasses_for_priority() -> None:
    async def scenario() -> None:
        written: list[tuple[str, bool]] = []

        async def writer(message: str, *, sensitive: bool = False) -> None:
            written.append((message, sensitive))

        sender = RateLimitedSender(
            writer, rate_per_second=1000, burst=2, queue_size=4
        )
        await sender.send("PING :before-start", priority=True)
        sender.start()
        try:
            await asyncio.gather(
                sender.send("PRIVMSG #test :one"),
                sender.send("PRIVMSG #test :two", sensitive=True),
            )
            await sender.send("PONG :priority", priority=True)
        finally:
            await sender.stop()

        assert written == [
            ("PING :before-start", False),
            ("PRIVMSG #test :one", False),
            ("PRIVMSG #test :two", True),
            ("PONG :priority", False),
        ]

    asyncio.run(scenario())


def test_sender_propagates_writer_failure() -> None:
    async def scenario() -> None:
        failures: list[Exception] = []

        async def writer(message: str, *, sensitive: bool = False) -> None:
            raise OSError("write failed")

        sender = RateLimitedSender(
            writer,
            rate_per_second=1,
            burst=1,
            queue_size=2,
            on_failure=failures.append,
        )
        sender.start()
        try:
            with pytest.raises(OSError, match="write failed"):
                await sender.send("PRIVMSG #test :failure")
            assert len(failures) == 1
        finally:
            await sender.stop()

    asyncio.run(scenario())
