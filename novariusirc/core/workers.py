"""Worker pool helpers."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable

from .config import WorkerConfig


class WorkerPool:
    def __init__(self, config: WorkerConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.executor = ProcessPoolExecutor(max_workers=config.processes)

    async def run_in_process(self, func: Callable[..., Any], *args: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, func, *args)

    async def shutdown(self) -> None:
        self.logger.info("Shutting down worker pool")
        self.executor.shutdown(wait=False)
