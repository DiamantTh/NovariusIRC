"""Connection-independent outbound IRC flow control."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Protocol


class LineWriter(Protocol):
    async def __call__(
        self, message: str, *, sensitive: bool = False
    ) -> None: ...


class RateLimitedSender:
    """Bounded token-bucket queue for normal IRC traffic.

    Priority traffic bypasses the queue for protocol keepalives and
    registration. The supplied writer remains responsible for the concrete
    stream and logging policy.
    """

    def __init__(
        self,
        writer: LineWriter,
        *,
        rate_per_second: float,
        burst: int,
        queue_size: int,
        enqueue_timeout: float = 5.0,
        on_failure: Callable[[Exception], None] | None = None,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("IRC send rate must be positive")
        if burst < 1 or queue_size < 1 or enqueue_timeout <= 0:
            raise ValueError("IRC sender limits must be positive")
        self.writer = writer
        self.rate_per_second = rate_per_second
        self.burst = burst
        self.queue_size = queue_size
        self.enqueue_timeout = enqueue_timeout
        self.on_failure = on_failure
        self._queue: asyncio.Queue[
            tuple[int, str, bool, asyncio.Future[None]]
        ] | None = None
        self._task: asyncio.Task[None] | None = None
        self._sequence = 0

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def queue_depth(self) -> int:
        """Return currently queued normal-priority IRC lines."""
        return self._queue.qsize() if self._queue is not None else 0

    def start(self) -> None:
        if self.is_running:
            return
        self._queue = asyncio.Queue(maxsize=self.queue_size)
        self._task = asyncio.create_task(self._run(), name="irc-send-queue")

    async def stop(self, error: Exception | None = None) -> None:
        task = self._task
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._task = None
        self._fail_pending(error or ConnectionError("IRC sender stopped"))
        self._queue = None

    async def send(
        self,
        message: str,
        *,
        sensitive: bool = False,
        priority: bool = False,
    ) -> None:
        queue = self._queue
        if priority or not self.is_running or queue is None:
            await self.writer(message, sensitive=sensitive)
            return

        result = asyncio.get_running_loop().create_future()
        self._sequence += 1
        item = (self._sequence, message, sensitive, result)
        try:
            await asyncio.wait_for(queue.put(item), timeout=self.enqueue_timeout)
        except TimeoutError as exc:
            raise ConnectionError("IRC send queue is full") from exc
        await result

    async def _run(self) -> None:
        assert self._queue is not None
        queue = self._queue
        tokens = float(self.burst)
        last_refill = time.monotonic()
        try:
            while True:
                _, message, sensitive, result = await queue.get()
                if result.cancelled():
                    queue.task_done()
                    continue
                try:
                    now = time.monotonic()
                    tokens = min(
                        float(self.burst),
                        tokens + (now - last_refill) * self.rate_per_second,
                    )
                    last_refill = now
                    if tokens < 1.0:
                        await asyncio.sleep((1.0 - tokens) / self.rate_per_second)
                        last_refill = time.monotonic()
                        tokens = 0.0
                    else:
                        tokens -= 1.0
                    await self.writer(message, sensitive=sensitive)
                except Exception as exc:  # noqa: BLE001 - transport boundary
                    if not result.done():
                        result.set_exception(exc)
                    if self.on_failure:
                        self.on_failure(exc)
                    self._fail_pending(exc)
                    return
                else:
                    if not result.done():
                        result.set_result(None)
                finally:
                    queue.task_done()
        finally:
            self._fail_pending(ConnectionError("IRC sender stopped"))

    def _fail_pending(self, error: Exception) -> None:
        queue = self._queue
        if queue is None:
            return
        while True:
            try:
                _, _, _, result = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not result.done():
                result.set_exception(error)
            queue.task_done()
