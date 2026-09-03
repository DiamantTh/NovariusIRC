from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import MethodType, SimpleNamespace

from novariusirc.core.config import DatabaseConfig, FeedDefinition, FeedsConfig
from novariusirc.core.database import SQLiteDatabase
from novariusirc.core.feeds import FeedEngine, FeedState
from novariusirc.core.moderation import ModerationManager


class FeedHTTPClientStub:
    """Small Tornado-client substitute for feed protocol tests."""

    def __init__(self, response: SimpleNamespace) -> None:
        self.response = response
        self.requests = []

    async def fetch(self, request, *, raise_error: bool):
        self.requests.append((request, raise_error))
        return self.response


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


def test_feed_engine_configures_tornado_body_limit(monkeypatch) -> None:
    created: dict[str, object] = {}

    class LifecycleClient:
        def close(self) -> None:
            created["closed"] = True

    def build_client(*, force_instance: bool, max_body_size: int) -> LifecycleClient:
        created["force_instance"] = force_instance
        created["max_body_size"] = max_body_size
        return LifecycleClient()

    monkeypatch.setattr("novariusirc.core.feeds.AsyncHTTPClient", build_client)
    engine = FeedEngine(
        FeedsConfig(enabled=True, max_body_size=4096), logging.getLogger("test")
    )

    asyncio.run(engine.start())
    asyncio.run(engine.stop())

    assert created == {
        "force_instance": True,
        "max_body_size": 4096,
        "closed": True,
    }


def test_feed_fetch_uses_tornado_request_limits_and_cache_headers() -> None:
    engine = FeedEngine(
        FeedsConfig(http_timeout=17, max_body_size=4096), logging.getLogger("test")
    )
    feed = FeedDefinition(name="first", url="https://one.test/feed", channel="#one")
    engine.add_feed(feed)
    engine.feed_states[feed.url] = FeedState(etag='"old"', last_modified="yesterday")
    client = FeedHTTPClientStub(
        SimpleNamespace(
            code=200,
            error=None,
            headers={"ETag": '"new"', "Last-Modified": "today"},
            body=b"""<?xml version=\"1.0\"?><rss><channel><item><guid>one</guid><title>One</title></item></channel></rss>""",
        )
    )
    engine.http_client = client  # type: ignore[assignment]
    announced: list[str] = []

    async def record(_feed: FeedDefinition, entry: dict) -> None:
        announced.append(entry["title"])

    engine.subscribe(record)
    asyncio.run(engine._poll_feed(feed))

    request, raise_error = client.requests[0]
    assert raise_error is False
    assert request.request_timeout == 17
    assert request.headers["If-None-Match"] == '"old"'
    assert request.headers["If-Modified-Since"] == "yesterday"
    assert announced == ["One"]
    assert engine.feed_states[feed.url].etag == '"new"'
    assert engine.feed_states[feed.url].last_modified == "today"


def test_feed_fetch_treats_not_modified_as_success_without_parsing() -> None:
    engine = FeedEngine(FeedsConfig(), logging.getLogger("test"))
    feed = FeedDefinition(name="first", url="https://one.test/feed", channel="#one")
    engine.add_feed(feed)
    client = FeedHTTPClientStub(
        SimpleNamespace(code=304, error=None, headers={}, body=b"not XML")
    )
    engine.http_client = client  # type: ignore[assignment]

    asyncio.run(engine._poll_feed(feed))

    assert engine.feed_states[feed.url].seen_ids == []
