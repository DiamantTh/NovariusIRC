"""Supervision for background work started by built-in modules."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any


class TaskSupervisor:
    """Own, observe, and stop tasks created by built-in modules."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger.getChild("tasks")
        self._tasks: dict[str, set[asyncio.Task[Any]]] = {}

    def create_task(
        self,
        owner: str,
        coroutine: Coroutine[Any, Any, Any],
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        task_name = name or f"module:{owner}"
        task = asyncio.create_task(coroutine, name=task_name)
        self._tasks.setdefault(owner, set()).add(task)
        task.add_done_callback(lambda completed: self._task_finished(owner, completed))
        return task

    def _task_finished(self, owner: str, task: asyncio.Task[Any]) -> None:
        tasks = self._tasks.get(owner)
        if tasks is not None:
            tasks.discard(task)
            if not tasks:
                self._tasks.pop(owner, None)
        if task.cancelled():
            return
        try:
            exception = task.exception()
        except asyncio.CancelledError:
            return
        if exception is not None:
            self.logger.error(
                "Background task %s for module %s failed: %s",
                task.get_name(),
                owner,
                exception,
                exc_info=exception,
            )

    async def cancel_owner(self, owner: str, *, timeout: float) -> None:
        tasks = tuple(self._tasks.get(owner, ()))
        for task in tasks:
            task.cancel()
        if not tasks:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=timeout
            )
        except TimeoutError:
            pending = [task.get_name() for task in tasks if not task.done()]
            self.logger.error(
                "Background tasks for module %s did not stop in time: %s",
                owner,
                ", ".join(pending),
            )

    async def shutdown(self, *, timeout: float) -> None:
        for owner in tuple(self._tasks):
            await self.cancel_owner(owner, timeout=timeout)
