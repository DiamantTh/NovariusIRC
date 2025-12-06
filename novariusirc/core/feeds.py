"""Feed engine for RSS/Atom polling."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Set

import aiohttp
import feedparser

from .config import FeedDefinition, FeedsConfig

Subscriber = Callable[[FeedDefinition, dict], Awaitable[None]]


@dataclass
class FeedState:
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    seen_ids: Set[str] = field(default_factory=set)


class FeedEngine:
    def __init__(self, config: FeedsConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild("feeds")
        self.session: Optional[aiohttp.ClientSession] = None
        self.subscribers: List[Subscriber] = []
        self.feed_states: Dict[str, FeedState] = {}
        self.feed_definitions: Dict[str, FeedDefinition] = {}
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    def add_feed(self, feed: FeedDefinition) -> None:
        if len(self.feed_definitions) >= self.config.max_feeds:
            self.logger.warning("Feed limit reached; cannot add feed %s", feed.url)
            return
        self.feed_definitions[feed.url] = feed
        self.feed_states.setdefault(feed.url, FeedState())
        self.logger.info("Registered feed %s -> channel %s", feed.name, feed.channel)

    def subscribe(self, callback: Subscriber) -> None:
        self.subscribers.append(callback)

    async def start(self) -> None:
        if not self.config.enabled:
            self.logger.info("Feed engine disabled")
            return
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=self.config.http_timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self.session:
            await self.session.close()
            self.session = None
        self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.gather(*(self._poll_feed(feed) for feed in self.feed_definitions.values()))
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.config.refresh_interval)
            except asyncio.TimeoutError:
                continue

    async def _poll_feed(self, feed: FeedDefinition) -> None:
        state = self.feed_states.setdefault(feed.url, FeedState())
        headers = {}
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified

        if not self.session:
            return

        try:
            async with self.session.get(feed.url, headers=headers) as resp:
                if resp.status == 304:
                    return
                if resp.status >= 400:
                    self.logger.warning("Feed %s returned HTTP %s", feed.url, resp.status)
                    return
                content = await resp.read()
                if len(content) > self.config.max_body_size:
                    self.logger.warning("Feed %s exceeded max body size (%s bytes)", feed.url, len(content))
                    return
                state.etag = resp.headers.get("ETag") or state.etag
                state.last_modified = resp.headers.get("Last-Modified") or state.last_modified
        except asyncio.TimeoutError:
            self.logger.warning("Timeout fetching feed %s", feed.url)
            return
        except Exception as exc:
            self.logger.warning("Failed to fetch feed %s: %s", feed.url, exc)
            return

        parsed = await asyncio.to_thread(feedparser.parse, content)
        entries = parsed.entries or []
        for entry in entries:
            entry_id = entry.get("id") or entry.get("link") or entry.get("title")
            if not entry_id:
                continue
            if entry_id in state.seen_ids:
                continue
            state.seen_ids.add(entry_id)
            self._trim_seen(state)
            await self._notify(feed, entry)

    def _trim_seen(self, state: FeedState) -> None:
        while len(state.seen_ids) > self.config.max_items_per_feed:
            state.seen_ids.pop()

    async def _notify(self, feed: FeedDefinition, entry: dict) -> None:
        if not self.subscribers:
            return
        for subscriber in self.subscribers:
            try:
                await subscriber(feed, entry)
            except Exception as exc:
                self.logger.error("Subscriber error for feed %s: %s", feed.url, exc)
