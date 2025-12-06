"""Warn-only moderation plugin with simple flood detection."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Deque, Dict, Tuple

from novariusirc.core.i18n import gettext_lazy as _
from novariusirc.core.plugins import Plugin


class Plugin(Plugin):
    name = "moderation"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._history: Dict[Tuple[str, str], Deque[datetime]] = defaultdict(deque)

    async def on_message(self, nick: str, channel: str, message: str) -> None:
        if not channel or self.config.moderation.mode == "off":
            return
        threshold = self.config.moderation.flood_threshold
        key = (channel.lower(), nick.lower())
        now = datetime.utcnow()
        history = self._history[key]
        history.append(now)
        self._prune(history, threshold.per_seconds)
        if len(history) > threshold.messages:
            await self._warn(nick, channel, len(history), threshold.messages)

    def _prune(self, history: Deque[datetime], seconds: int) -> None:
        cutoff = datetime.utcnow() - timedelta(seconds=seconds)
        while history and history[0] < cutoff:
            history.popleft()

    async def _warn(self, nick: str, channel: str, count: int, limit: int) -> None:
        if self.config.moderation.mode != "warn":
            return
        if not self.client:
            return
        text = _("Flood warning for {nick} in {channel} ({count}/{limit})").format(
            nick=nick, channel=channel, count=count, limit=limit
        )
        targets = self.config.moderation.warn_targets or [channel]
        for target in targets:
            await self.client.send_privmsg(target, text)
        self.logger.warning("Flood warning triggered for %s in %s", nick, channel)
        # Small delay to avoid hammering targets
        await asyncio.sleep(0.1)
