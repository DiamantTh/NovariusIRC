"""RSS announcer plugin."""

from __future__ import annotations

from novariusirc.core.i18n import gettext_lazy as _
from novariusirc.core.plugins import Plugin


class Plugin(Plugin):
    name = "rss_announcer"

    async def start(self) -> None:
        if not self.config.feeds.enabled:
            return
        for feed in self.config.feeds.feeds:
            self.feeds.add_feed(feed)
        self.feeds.subscribe(self._announce)

    async def _announce(self, feed, entry) -> None:
        if not self.client:
            return
        title = entry.get("title") or _("New item")
        link = entry.get("link") or ""
        summary = entry.get("summary") or ""
        message = f"[{feed.name}] {title}"
        if summary:
            message = f"{message} – {summary}"
        if link:
            message = f"{message} {link}"
        await self.client.send_privmsg(feed.channel, message)
