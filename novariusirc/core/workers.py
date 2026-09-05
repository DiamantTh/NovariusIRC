"""Worker pool helpers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from .config import WorkerConfig


def _configure_worker(memory_mebibytes: int | None) -> None:
    """Apply an optional per-child address-space limit on supported systems."""
    if memory_mebibytes is None:
        return
    try:
        import resource

        limit = memory_mebibytes * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, OSError, ValueError):
        # Windows and constrained platforms have no portable RLIMIT_AS.
        return


class WorkerPool:
    def __init__(self, config: WorkerConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.executor = ProcessPoolExecutor(
            max_workers=config.processes,
            max_tasks_per_child=config.max_tasks_per_child,
            initializer=_configure_worker,
            initargs=(config.max_memory_mebibytes,),
        )

    async def run_in_process(self, func: Callable[..., Any], *args: Any) -> Any:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self.executor, func, *args)
        try:
            return await asyncio.wait_for(future, timeout=self.config.task_timeout_seconds)
        except TimeoutError as exc:
            self.logger.error("Worker task exceeded %.1fs", self.config.task_timeout_seconds)
            raise TimeoutError("worker task timed out") from exc

    async def shutdown(self) -> None:
        self.logger.info("Shutting down worker pool")
        await asyncio.to_thread(self.executor.shutdown, wait=True, cancel_futures=True)
