"""Logging utilities."""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path

from .config import LoggingConfig, PathsConfig

# IRC formatting codes to strip
IRC_FORMAT_REGEX = re.compile(
    r"\x02|\x1D|\x1F|\x16|\x0F|\x03(?:\d{1,2}(?:,\d{1,2})?)?|\x04[0-9A-Fa-f]{6}(?:,[0-9A-Fa-f]{6})?"
)


def strip_irc_formatting(text: str) -> str:
    """Remove IRC formatting codes from text.
    
    Strips:
        \x02 - Bold
        \x1D - Italic
        \x1F - Underline
        \x16 - Reverse
        \x0F - Reset
        \x03 - Color (with optional fg/bg)
        \x04 - Hex color
    """
    return IRC_FORMAT_REGEX.sub("", text)


class IRCLogHandler(TimedRotatingFileHandler):
    """Custom handler that writes date header on file rotation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_date = datetime.utcnow().date()
        self._write_header_on_next = self._should_write_header()

    def _should_write_header(self) -> bool:
        """Check if file is empty or doesn't exist."""
        try:
            return not Path(self.baseFilename).exists() or Path(self.baseFilename).stat().st_size == 0
        except Exception:
            return True

    def emit(self, record: logging.LogRecord) -> None:
        """Emit log record with date header if file is new."""
        # Check if day changed (rotation happened)
        current_date = datetime.utcnow().date()
        if current_date != self._current_date:
            self._current_date = current_date
            self._write_header_on_next = True

        # Write header if needed
        if self._write_header_on_next:
            try:
                with open(self.baseFilename, "a", encoding="utf-8") as f:
                    f.write(f"# Log started: {current_date}\n")
                self._write_header_on_next = False
            except Exception:
                pass

        super().emit(record)


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


def channel_log_path(network_name: str, channel: str, paths: PathsConfig) -> Path:
    sanitized_channel = channel.lstrip("#").replace("/", "_")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    root = Path(paths.log_root).expanduser()
    return root / network_name / sanitized_channel / f"{today}.log"


def get_channel_logger(network_name: str, channel: str, paths: PathsConfig) -> logging.Logger:
    logger_name = f"channel.{network_name}.{channel}"
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    path = channel_log_path(network_name, channel, paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = IRCLogHandler(path, when="midnight", backupCount=14)
    handler.setFormatter(logging.Formatter(fmt="[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def pm_log_path(network_name: str, nick: str, paths: PathsConfig) -> Path:
    """Get log path for private messages."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    root = Path(paths.log_root).expanduser()
    return root / network_name / nick / f"{today}.log"


def get_pm_logger(network_name: str, nick: str, paths: PathsConfig) -> logging.Logger:
    """Get logger for private messages (PRIVMSG + NOTICE to bot)."""
    logger_name = f"pm.{network_name}.{nick}"
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    path = pm_log_path(network_name, nick, paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = IRCLogHandler(path, when="midnight", backupCount=14)
    handler.setFormatter(logging.Formatter(fmt="[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def raw_log_path(network_name: str, paths: PathsConfig) -> Path:
    """Get log path for raw IRC protocol lines."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    root = Path(paths.log_root).expanduser()
    return root / network_name / "_raw" / f"{today}.log"


def get_raw_logger(network_name: str, paths: PathsConfig) -> logging.Logger:
    """Get logger for raw IRC protocol (only active when DEBUG level)."""
    logger_name = f"raw.{network_name}"
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    path = raw_log_path(network_name, paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(path, when="midnight", backupCount=7)
    handler.setFormatter(logging.Formatter(fmt="%(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"))
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get logger by name."""
    return logging.getLogger(name)


def log_channel_event(network_name: str, channel: str, paths: PathsConfig, message: str) -> None:
    """Log an event to channel log (JOIN/PART/QUIT/NICK/MODE/KICK/TOPIC)."""
    logger = get_channel_logger(network_name, channel, paths)
    logger.info("*** %s", message)


def log_pm_event(network_name: str, nick: str, paths: PathsConfig, message: str) -> None:
    """Log an event to PM log (QUIT/DCC)."""
    logger = get_pm_logger(network_name, nick, paths)
    logger.info("*** %s", message)


def log_channel_event(network_name: str, channel: str, paths: PathsConfig, message: str) -> None:
    """Log an event to channel log (JOIN/PART/QUIT/NICK/MODE/KICK/TOPIC)."""
    logger = get_channel_logger(network_name, channel, paths)
    logger.info("*** %s", message)
