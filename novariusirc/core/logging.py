"""Logging utilities."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path

from .config import LoggingConfig, PathsConfig


def _structured_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt='ts=%(asctime)s level=%(levelname)s logger=%(name)s msg="%(message)s"',
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )


def setup_logging(config: LoggingConfig, paths: PathsConfig) -> logging.Logger:
    log_root = Path(paths.log_root or config.log_dir).expanduser()
    log_root.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = []
    formatter = _structured_formatter()

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    handlers.append(stream)

    file_handler = RotatingFileHandler(log_root / "novariusirc.log", maxBytes=5 * 1024 * 1024, backupCount=3)
    file_handler.setFormatter(formatter)
    handlers.append(file_handler)

    if config.journald_enabled:
        try:
            from systemd.journal import JournalHandler

            journal_handler = JournalHandler()
            journal_handler.setFormatter(formatter)
            handlers.append(journal_handler)
        except Exception:
            # journald is optional; continue without it if not available
            pass

    logging.basicConfig(
        level=getattr(logging, config.level.upper(), logging.INFO),
        handlers=handlers,
        force=True,
    )
    return logging.getLogger("novariusirc")


def channel_log_path(server: str, channel: str, paths: PathsConfig) -> Path:
    sanitized_channel = channel.lstrip("#").replace("/", "_")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    root = Path(paths.log_root).expanduser()
    return root / server / sanitized_channel / f"{today}.log"


def get_channel_logger(server: str, channel: str, paths: PathsConfig) -> logging.Logger:
    logger_name = f"channel.{server}.{channel}"
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    path = channel_log_path(server, channel, paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(path, when="midnight", backupCount=14)
    handler.setFormatter(logging.Formatter(fmt="%(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
