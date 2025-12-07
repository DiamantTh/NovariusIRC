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
        data = {
            "feed": feed.name,
            "title": entry.get("title") or _("New item"),
            "summary": entry.get("summary") or "",
            "link": entry.get("link") or "",
            "published": entry.get("published") or entry.get("updated") or "",
        }
        template = feed.template or "[{feed}] {title} – {summary} {link}"
        message = self._safe_format(template, data).strip()
        await self.client.send_privmsg(feed.channel, message)

    @staticmethod
    def _safe_format(template: str, data: dict) -> str:
        class SafeDict(dict):
            def __missing__(self, key: str) -> str:
                return ""

        return template.format_map(SafeDict(data))
