"""Feed engine for RSS/Atom polling."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import random
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp
import feedparser

from .config import FeedDefinition, FeedsConfig

Subscriber = Callable[[FeedDefinition, dict], Awaitable[None]]


@dataclass
class FeedState:
    etag: str | None = None
    last_modified: str | None = None
    seen_ids: list[str] = field(default_factory=list)


class FeedEngine:
    def __init__(
        self,
        config: FeedsConfig,
        logger: logging.Logger,
        data_root: Path | None = None,
    ):
        self.config = config
        self.logger = logger.getChild("feeds")
        self.session: aiohttp.ClientSession | None = None
        self.subscribers: list[Subscriber] = []
        self.feed_states: dict[str, FeedState] = {}
        self.feed_definitions: dict[str, FeedDefinition] = {}
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._poll_lock = asyncio.Lock()
        self._user_agent_index = 0
        self._user_agents = config.user_agents or [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5_0)",
            "Mozilla/5.0 (X11; Linux x86_64)",
        ]
        self._state_dir = data_root / "feeds" if data_root else None
        if self._state_dir:
            self._state_dir.mkdir(parents=True, exist_ok=True)

    def add_feed(self, feed: FeedDefinition) -> None:
        if not feed.enabled:
            self.logger.info("Feed %s is disabled; skipping registration", feed.name)
            return
        if len(self.feed_definitions) >= self.config.max_feeds:
            self.logger.warning("Feed limit reached; cannot add feed %s", feed.url)
            return
        self.feed_definitions[feed.url] = feed
        self.feed_states.setdefault(feed.url, self._load_state(feed.url) or FeedState())
        self.logger.info("Registered feed %s -> channel %s", feed.name, feed.channel)

    def subscribe(self, callback: Subscriber) -> None:
        if callback not in self.subscribers:
            self.subscribers.append(callback)

    def unsubscribe(self, callback: Subscriber) -> None:
        with contextlib.suppress(ValueError):
            self.subscribers.remove(callback)

    async def start(self) -> None:
        if not self.config.enabled:
            self.logger.info("Feed engine disabled")
            return
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=self.config.http_timeout)
            connector = aiohttp.TCPConnector(ssl=self._ssl_context())
            self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
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
            async with self._poll_lock:
                await asyncio.gather(
                    *(
                        self._poll_feed(
                            feed,
                            max_items=feed.max_items_per_poll
                            if feed.max_items_per_poll is not None
                            else self.config.max_items_per_poll,
                        )
                        for feed in self.feed_definitions.values()
                    )
                )
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.config.refresh_interval
                )
            except TimeoutError:
                continue

    async def poll_now(self, max_items: int | None = None) -> None:
        """Manually poll all feeds once.

        Args:
            max_items: Maximum items per feed; defaults to the manual limit.
        """
        async with self._poll_lock:
            await asyncio.gather(
                *(
                    self._poll_feed(
                        feed,
                        max_items=(
                            max_items
                            if max_items is not None
                            else (
                                feed.max_items_per_manual
                                if feed.max_items_per_manual is not None
                                else self.config.max_items_per_manual
                            )
                        ),
                    )
                    for feed in self.feed_definitions.values()
                )
            )

    async def _poll_feed(
        self, feed: FeedDefinition, max_items: int | None = None
    ) -> None:
        state = self.feed_states.setdefault(feed.url, FeedState())
        headers = {}
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified
        headers["User-Agent"] = self._next_user_agent()

        if not self.session:
            return

        try:
            async with self.session.get(feed.url, headers=headers) as resp:
                if resp.status == 304:
                    return
                if resp.status >= 400:
                    self.logger.warning(
                        "Feed %s returned HTTP %s", feed.url, resp.status
                    )
                    return
                content = await resp.content.read(self.config.max_body_size + 1)
                if len(content) > self.config.max_body_size:
                    self.logger.warning(
                        "Feed %s exceeded max body size (%s bytes)",
                        feed.url,
                        len(content),
                    )
                    return
                state.etag = resp.headers.get("ETag") or state.etag
                state.last_modified = (
                    resp.headers.get("Last-Modified") or state.last_modified
                )
        except TimeoutError:
            self.logger.warning("Timeout fetching feed %s", feed.url)
            return
        except (aiohttp.ClientError, OSError) as exc:
            self.logger.warning("Failed to fetch feed %s: %s", feed.url, exc)
            return

        parsed = await asyncio.to_thread(feedparser.parse, content)
        entries = parsed.entries or []
        unseen_entries = self._select_unseen(state, entries)
        limit = max_items if max_items is not None else self.config.max_items_per_poll
        for entry in unseen_entries[:limit]:
            await self._notify(feed, entry)
        self._save_state(feed.url, state)

    def _select_unseen(self, state: FeedState, entries: list[dict]) -> list[dict]:
        known_ids = set(state.seen_ids)
        current_ids: list[str] = []
        unseen_entries: list[dict] = []
        for entry in entries:
            entry_id = entry.get("id") or entry.get("link") or entry.get("title")
            if not entry_id:
                continue
            current_ids.append(entry_id)
            if entry_id not in known_ids:
                unseen_entries.append(entry)

        state.seen_ids = list(dict.fromkeys([*current_ids, *state.seen_ids]))[
            : self.config.max_items_per_feed
        ]
        return unseen_entries

    def _state_file(self, url: str) -> Path | None:
        if not self._state_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._state_dir / f"{digest}.json"

    def _load_state(self, url: str) -> FeedState | None:
        state_file = self._state_file(url)
        if not state_file or not state_file.exists():
            return None
        try:
            with state_file.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return FeedState(
                etag=data.get("etag"),
                last_modified=data.get("last_modified"),
                seen_ids=list(dict.fromkeys(data.get("seen_ids", []))),
            )
        except (
            OSError,
            json.JSONDecodeError,
            AttributeError,
            TypeError,
            ValueError,
        ) as exc:
            self.logger.warning("Failed to load feed state for %s: %s", url, exc)
            return None

    def _save_state(self, url: str, state: FeedState) -> None:
        state_file = self._state_file(url)
        if not state_file:
            return
        try:
            payload = {
                "etag": state.etag,
                "last_modified": state.last_modified,
                "seen_ids": list(state.seen_ids),
            }
            with state_file.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh)
        except (OSError, TypeError, ValueError) as exc:
            self.logger.warning("Failed to save feed state for %s: %s", url, exc)

    async def _notify(self, feed: FeedDefinition, entry: dict) -> None:
        if not self.subscribers:
            return
        for subscriber in self.subscribers:
            try:
                await subscriber(feed, entry)
            except Exception as exc:  # noqa: BLE001 - isolate third-party callbacks
                self.logger.error("Subscriber error for feed %s: %s", feed.url, exc)

    def _ssl_context(self) -> ssl.SSLContext | None:
        if not any(
            [
                self.config.tls_allow_legacy,
                self.config.tls_ca_file,
                self.config.tls_ca_dir,
                self.config.tls_cert_file,
                self.config.tls_key_file,
            ]
        ):
            return None
        context = ssl.create_default_context(
            cafile=self.config.tls_ca_file, capath=self.config.tls_ca_dir
        )
        if self.config.tls_cert_file:
            context.load_cert_chain(
                self.config.tls_cert_file, keyfile=self.config.tls_key_file
            )
        if self.config.tls_allow_legacy:
            context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
        return context

    def _next_user_agent(self) -> str:
        if not self._user_agents:
            return "NovariusIRC/feeds"
        mode = self.config.user_agent_rotate.lower()
        if mode == "random":
            return random.choice(self._user_agents)
        if mode == "fixed":
            return self._user_agents[0]
        # default: rotate through list
        ua = self._user_agents[self._user_agent_index % len(self._user_agents)]
        self._user_agent_index += 1
        return ua
