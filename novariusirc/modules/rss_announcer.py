"""RSS announcer plugin."""

from __future__ import annotations

from datetime import datetime

from novariusirc.core.i18n import gettext_lazy as _
from novariusirc.core.plugins import Plugin


class Plugin(Plugin):
    name = "rss_announcer"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_sent: dict[tuple[str, str], datetime] = {}

    async def start(self) -> None:
        if not self.config.feeds.enabled:
            return
        for feed in self.config.feeds.feeds:
            if not feed.enabled:
                self.logger.info("Skipping disabled feed %s", feed.name)
                continue
            self.feeds.add_feed(feed)
        self.feeds.subscribe(self._announce)
        self.commands.register(
            "rssfetch",
            self._cmd_rssfetch,
            roles=("admin",),
            help_text="Fetch RSS/ATOM feeds now (optional limit).",
        )

    async def _cmd_rssfetch(self, ctx, args) -> None:
        limit = None
        if args:
            try:
                limit = max(1, int(args[0]))
            except ValueError:
                await ctx.reply("Usage: !rssfetch [limit]")
                return
        await self.feeds.poll_now(limit)
        await ctx.reply("RSS/ATOM fetch triggered.")

    async def _announce(self, feed, entry) -> None:
        if not self.client:
            return
        channels = feed.channels or ([feed.channel] if feed.channel else [])
        if not channels:
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
        now = datetime.now()
        for channel in channels:
            interval = feed.per_channel_interval.get(channel, feed.min_interval_seconds)
            if interval:
                last_sent = self._last_sent.get((feed.url, channel))
                if last_sent and (now - last_sent).total_seconds() < interval:
                    continue
            await self.client.send_privmsg(channel, message)
            self._last_sent[(feed.url, channel)] = now

    @staticmethod
    def _safe_format(template: str, data: dict) -> str:
        class SafeDict(dict):
            def __missing__(self, key: str) -> str:
                return ""

        return template.format_map(SafeDict(data))
