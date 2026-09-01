from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import MethodType

from novariusirc.core.config import DatabaseConfig, FeedDefinition, FeedsConfig
from novariusirc.core.database import SQLiteDatabase
from novariusirc.core.feeds import FeedEngine, FeedState
from novariusirc.core.moderation import ModerationManager


def test_rate_limit_counts_messages_and_warnings_escalate() -> None:
    manager = ModerationManager(
        {
            "enabled": True,
            "rate_limit": {
                "enabled": True,
                "messages_per_minute": 1,
                "action": "warn",
            },
            "warnings": {"enabled": True, "to_kick": 2, "to_ban": 3},
        }
    )

    assert asyncio.run(manager.check_message("Alice", "#one", "first")) is None
    violation = asyncio.run(manager.check_message("Alice", "#one", "second"))
    assert violation == ("warn", "Rate limit exceeded (1 msgs/min)")
    action, reason = violation
    first = asyncio.run(manager.apply_action(action, "Alice", "#one", reason))
    assert first == ["NOTICE Alice :Rate limit exceeded (1 msgs/min) (Warning 1)"]

    second = asyncio.run(manager.apply_action(action, "Alice", "#one", reason))
    assert second == ["KICK #one Alice :Accumulated 2 warnings"]


def test_ban_is_channel_scoped_and_sets_mode_before_kick() -> None:
    manager = ModerationManager()
    commands = asyncio.run(manager.apply_action("ban", "Alice", "#one", "reason"))
    assert commands == [
        "MODE #one +b Alice!*@*",
        "KICK #one Alice :reason",
    ]
    assert asyncio.run(manager.check_message("Alice", "#one", "x")) == (
        "ban",
        "User is banned",
    )
    assert asyncio.run(manager.check_message("Alice", "#two", "x")) is None


def test_manual_feed_limits_are_resolved_per_feed() -> None:
    config = FeedsConfig(max_items_per_manual=4)
    engine = FeedEngine(config, logging.getLogger("test.feeds"))
    first = FeedDefinition(name="first", url="https://one.test", channel="#one")
    second = FeedDefinition(
        name="second",
        url="https://two.test",
        channel="#two",
        max_items_per_manual=7,
    )
    engine.add_feed(first)
    engine.add_feed(second)
    calls: list[tuple[str, int | None]] = []

    async def record(self, feed: FeedDefinition, max_items: int | None = None) -> None:
        calls.append((feed.name, max_items))

    engine._poll_feed = MethodType(record, engine)
    asyncio.run(engine.poll_now())
    assert sorted(calls) == [("first", 4), ("second", 7)]

    calls.clear()
    asyncio.run(engine.poll_now(2))
    assert sorted(calls) == [("first", 2), ("second", 2)]


def test_feed_limit_does_not_backfill_old_items_on_later_polls() -> None:
    engine = FeedEngine(FeedsConfig(max_items_per_poll=1), logging.getLogger("test"))
    state = FeedState()
    entries = [{"id": "3"}, {"id": "2"}, {"id": "1"}]

    first_unseen = engine._select_unseen(state, entries)
    second_unseen = engine._select_unseen(state, entries)

    assert [entry["id"] for entry in first_unseen[:1]] == ["3"]
    assert second_unseen == []
    assert state.seen_ids == ["3", "2", "1"]


def test_feed_engine_uses_database_state(tmp_path: Path) -> None:
    database = SQLiteDatabase(DatabaseConfig(path=str(tmp_path / "bot.sqlite3")), "TestBot")
    database.initialize(create=True)
    engine = FeedEngine(
        FeedsConfig(),
        logging.getLogger("test.feeds"),
        data_root=tmp_path,
        state_store=database,
    )
    feed = FeedDefinition(name="first", url="https://one.test/feed", channel="#one")
    engine.add_feed(feed)
    engine.feed_states[feed.url] = FeedState(etag="one", seen_ids=["a", "b"])

    engine._save_state(feed.url, engine.feed_states[feed.url])

    restored = FeedEngine(
        FeedsConfig(),
        logging.getLogger("test.feeds"),
        data_root=tmp_path,
        state_store=database,
    )
    restored.add_feed(feed)
    asyncio.run(restored._restore_states())

    assert restored.feed_states[feed.url] == FeedState(etag="one", seen_ids=["a", "b"])
