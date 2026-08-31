from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from novariusirc.core.config import LoggingConfig, PathsConfig
from novariusirc.core.logging import (
    channel_log_path,
    get_channel_logger,
    log_irc,
    pm_log_path,
    raw_log_path,
    setup_logging,
    setup_moderation_logging,
)


def test_log_paths_use_the_documented_layout(tmp_path: Path) -> None:
    paths = PathsConfig(log_root=str(tmp_path))
    today = datetime.now(UTC).strftime("%Y-%m-%d") + ".log"

    assert channel_log_path("TestNet", "#room", paths) == (
        tmp_path / "irc" / "TestNet" / "channels" / "room" / today
    )
    assert pm_log_path("TestNet", "Alice", paths) == (
        tmp_path / "irc" / "TestNet" / "private" / "Alice" / today
    )
    assert raw_log_path("TestNet", paths) == (
        tmp_path / "irc" / "TestNet" / "raw" / today
    )


def test_core_log_is_separate_from_irc_logs(tmp_path: Path) -> None:
    setup_logging(LoggingConfig(), PathsConfig(log_root=str(tmp_path)))
    assert (tmp_path / "core" / "novariusirc.log").is_file()


def test_moderation_log_has_a_dedicated_handler(tmp_path: Path) -> None:
    log_file = tmp_path / "moderation" / "moderation.log"
    logger = setup_moderation_logging(str(log_file))
    logger.info("moderation decision")
    assert "moderation decision" in log_file.read_text(encoding="utf-8")


def test_irc_log_uses_server_time_in_the_configured_timezone(tmp_path: Path) -> None:
    paths = PathsConfig(log_root=str(tmp_path))
    logger = get_channel_logger("TestNet", "#room", paths, timezone="Europe/Berlin")
    log_irc(
        logger,
        "<Alice> hello",
        event_time=datetime(2026, 1, 1, 12, 34, 56, tzinfo=UTC),
    )

    log_file = channel_log_path("TestNet", "#room", paths)
    assert "[13:34:56] <Alice> hello" in log_file.read_text(encoding="utf-8")
