"""Bounded reading primitives for an established IRC stream."""

from __future__ import annotations

import asyncio

MAX_INCOMING_BYTES = 8703  # 8191 bytes of tags plus a 512-byte IRC message.


class IncompleteIRCLine(ConnectionError):
    """The stream ended with a line that had no LF terminator."""


class OversizedIRCLine(ValueError):
    def __init__(self, size: int):
        self.size = size
        super().__init__(f"Incoming IRC message is oversized ({size} bytes)")


class IRCLineReader:
    """Read complete, bounded UTF-8 IRC lines with an idle timeout."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        *,
        idle_timeout: float,
        maximum_bytes: int = MAX_INCOMING_BYTES,
    ) -> None:
        if idle_timeout <= 0 or maximum_bytes < 512:
            raise ValueError("IRC line reader limits must be positive")
        self.reader = reader
        self.idle_timeout = idle_timeout
        self.maximum_bytes = maximum_bytes

    async def read(self) -> str | None:
        try:
            raw = await asyncio.wait_for(
                self.reader.readline(), timeout=self.idle_timeout
            )
        except TimeoutError as exc:
            raise ConnectionError(
                f"IRC connection received no data for {self.idle_timeout:g} seconds"
            ) from exc
        except ValueError as exc:
            raise ConnectionError("Incoming IRC message exceeds the wire limit") from exc
        if not raw:
            return None
        if not raw.endswith(b"\n"):
            raise IncompleteIRCLine("Incomplete IRC message at end of stream")
        if len(raw) > self.maximum_bytes:
            raise OversizedIRCLine(len(raw))
        return raw.decode("utf-8", errors="replace").rstrip("\r\n")
