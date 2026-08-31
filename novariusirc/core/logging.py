"""Logging utilities."""

from __future__ import annotations

import logging
import re
import sys
from datetime import date, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import LoggingConfig, PathsConfig

# IRC formatting codes to strip
IRC_FORMAT_REGEX = re.compile(
    r"\x02|\x1D|\x1F|\x16|\x0F|\x03(?:\d{1,2}(?:,\d{1,2})?)?|\x04[0-9A-Fa-f]{6}(?:,[0-9A-Fa-f]{6})?"
)


def strip_irc_formatting(text: str) -> str:
    """Remove IRC formatting codes from text.

    Strips:
        \x02 - Bold
        \x1d - Italic
        \x1f - Underline
        \x16 - Reverse
        \x0f - Reset
        \x03 - Color (with optional fg/bg)
        \x04 - Hex color
    """
    return IRC_FORMAT_REGEX.sub("", text)


class DailyLogHandler(logging.Handler):
    """Write each record to the calendar-day file of its event timestamp."""

    def __init__(
        self,
        directory: Path,
        *,
        timezone: str,
        retention_days: int,
        write_header: bool = True,
    ):
        super().__init__()
        self.directory = directory
        self.timezone = ZoneInfo(timezone)
        self.retention_days = retention_days
        self.write_header = write_header

    def emit(self, record: logging.LogRecord) -> None:
        try:
            event_time = datetime.fromtimestamp(record.created, self.timezone)
            log_date = event_time.date()
            path = self.directory / f"{log_date:%Y-%m-%d}.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            needs_header = self.write_header and (
                not path.exists() or path.stat().st_size == 0
            )
            with path.open("a", encoding="utf-8") as handle:
                if needs_header:
                    handle.write(f"# Log started: {log_date}\n")
                handle.write(self.format(record) + "\n")
            self._remove_expired_files(log_date)
        except OSError:
            self.handleError(record)

    def _remove_expired_files(self, current_date) -> None:
        for path in self.directory.glob("????-??-??.log"):
            try:
                file_date = date.fromisoformat(path.stem)
                if (current_date - file_date).days > self.retention_days:
                    path.unlink()
            except (OSError, ValueError):
                continue


class IRCFormatter(logging.Formatter):
    """Format IRC logs in the instance timezone rather than host-local time."""

    def __init__(self, *args, timezone: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.timezone = ZoneInfo(timezone)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        timestamp = datetime.fromtimestamp(record.created, self.timezone)
        return timestamp.strftime(datefmt) if datefmt else timestamp.isoformat()


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

    core_log_path = log_root / "core" / "novariusirc.log"
    core_log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        core_log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
    )
    file_handler.setFormatter(formatter)
    handlers.append(file_handler)

    if config.journald_enabled:
        try:
            from systemd.journal import JournalHandler

            journal_handler = JournalHandler()
            journal_handler.setFormatter(formatter)
            handlers.append(journal_handler)
        except Exception as exc:  # noqa: BLE001 - optional integration must not stop startup
            logging.getLogger(__name__).warning("journald logging unavailable: %s", exc)

    logging.basicConfig(
        level=getattr(logging, config.level.upper(), logging.INFO),
        handlers=handlers,
        force=True,
    )
    return logging.getLogger("novariusirc")


def setup_moderation_logging(log_file: str) -> logging.Logger:
    """Write moderation decisions to their dedicated rotating log file."""
    logger = logging.getLogger("novariusirc.core.moderation")
    path = Path(log_file).expanduser()
    resolved_path = path.resolve()
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == resolved_path:
            return logger

    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=14)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s level=%(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _safe_component(value: str, fallback: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip().lstrip("#"))
    sanitized = sanitized.strip(".")
    return sanitized or fallback


def channel_log_path(
    network_name: str, channel: str, paths: PathsConfig, timezone: str = "Europe/Berlin"
) -> Path:
    sanitized_channel = _safe_component(channel, "channel")
    today = datetime.now(ZoneInfo(timezone)).strftime("%Y-%m-%d")
    root = Path(paths.log_root).expanduser()
    return (
        root
        / "irc"
        / _safe_component(network_name, "network")
        / "channels"
        / sanitized_channel
        / f"{today}.log"
    )


def get_channel_logger(
    network_name: str, channel: str, paths: PathsConfig, timezone: str = "Europe/Berlin"
) -> logging.Logger:
    logger_name = f"channel.{Path(paths.log_root).resolve()}.{network_name}.{channel}"
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    path = channel_log_path(network_name, channel, paths, timezone)
    handler = DailyLogHandler(path.parent, timezone=timezone, retention_days=14)
    handler.setFormatter(
        IRCFormatter(
            fmt="[%(asctime)s] %(message)s", datefmt="%H:%M:%S", timezone=timezone
        )
    )
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def pm_log_path(
    network_name: str, nick: str, paths: PathsConfig, timezone: str = "Europe/Berlin"
) -> Path:
    """Get log path for private messages."""
    today = datetime.now(ZoneInfo(timezone)).strftime("%Y-%m-%d")
    root = Path(paths.log_root).expanduser()
    return (
        root
        / "irc"
        / _safe_component(network_name, "network")
        / "private"
        / _safe_component(nick, "nick")
        / f"{today}.log"
    )


def get_pm_logger(
    network_name: str, nick: str, paths: PathsConfig, timezone: str = "Europe/Berlin"
) -> logging.Logger:
    """Get logger for private messages (PRIVMSG + NOTICE to bot)."""
    logger_name = f"pm.{Path(paths.log_root).resolve()}.{network_name}.{nick}"
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    path = pm_log_path(network_name, nick, paths, timezone)
    handler = DailyLogHandler(path.parent, timezone=timezone, retention_days=14)
    handler.setFormatter(
        IRCFormatter(
            fmt="[%(asctime)s] %(message)s", datefmt="%H:%M:%S", timezone=timezone
        )
    )
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def raw_log_path(
    network_name: str, paths: PathsConfig, timezone: str = "Europe/Berlin"
) -> Path:
    """Get log path for raw IRC protocol lines."""
    today = datetime.now(ZoneInfo(timezone)).strftime("%Y-%m-%d")
    root = Path(paths.log_root).expanduser()
    return (
        root
        / "irc"
        / _safe_component(network_name, "network")
        / "raw"
        / f"{today}.log"
    )


def get_raw_logger(
    network_name: str, paths: PathsConfig, timezone: str = "Europe/Berlin"
) -> logging.Logger:
    """Get logger for raw IRC protocol (only active when DEBUG level)."""
    logger_name = f"raw.{Path(paths.log_root).resolve()}.{network_name}"
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    path = raw_log_path(network_name, paths, timezone)
    handler = DailyLogHandler(
        path.parent, timezone=timezone, retention_days=7, write_header=False
    )
    handler.setFormatter(
        IRCFormatter(
            fmt="%(asctime)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
            timezone=timezone,
        )
    )
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get logger by name."""
    return logging.getLogger(name)


def log_irc(
    logger: logging.Logger,
    message: str,
    *args: object,
    event_time: datetime | None = None,
) -> None:
    """Log an IRC event using its server time when the server supplied one."""
    if event_time is None:
        logger.info(message, *args)
        return
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        "",
        0,
        message,
        args,
        None,
    )
    record.created = event_time.timestamp()
    record.msecs = (record.created - int(record.created)) * 1000
    logger.handle(record)


def log_pm_event(
    network_name: str,
    nick: str,
    paths: PathsConfig,
    message: str,
    event_time: datetime | None = None,
    timezone: str = "Europe/Berlin",
) -> None:
    """Log an event to PM log (QUIT/DCC)."""
    logger = get_pm_logger(network_name, nick, paths, timezone)
    log_irc(logger, "*** %s", message, event_time=event_time)


def log_channel_event(
    network_name: str,
    channel: str,
    paths: PathsConfig,
    message: str,
    event_time: datetime | None = None,
    timezone: str = "Europe/Berlin",
) -> None:
    """Log an event to channel log (JOIN/PART/QUIT/NICK/MODE/KICK/TOPIC)."""
    logger = get_channel_logger(network_name, channel, paths, timezone)
    log_irc(logger, "*** %s", message, event_time=event_time)
