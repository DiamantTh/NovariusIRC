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
        self.commands.register(
            "feed",
            self._cmd_feed,
            roles=("user",),
            help_text="Show feed overview. Usage: !feed list [query]",
        )

    async def _cmd_rssfetch(self, ctx, args) -> None:
        limit = None
        if args:
            try:
                limit = max(1, int(args[0]))
            except ValueError:
                await ctx.reply(_("Usage: !rssfetch [limit]"))
                return
        await self.feeds.poll_now(limit)
        await ctx.reply(_("RSS/ATOM fetch triggered."))

    async def _cmd_feed(self, ctx, args) -> None:
        if not self.config.feeds.enabled:
            await ctx.reply(_("Feeds are disabled."))
            return

        if not args or args[0].lower() not in {"list", "ls"}:
            await ctx.reply(_("Usage: !feed list [query]"))
            return

        query = " ".join(args[1:]).strip().lower()
        feeds = list(self.feeds.feed_definitions.values())
        if query:
            def _matches(feed) -> bool:
                channels = feed.channels or ([feed.channel] if feed.channel else [])
                haystack = " ".join([feed.name, feed.url, " ".join(channels)]).lower()
                return query in haystack

            feeds = [feed for feed in feeds if _matches(feed)]

        if not feeds:
            await ctx.reply(_("No feeds matched your query."))
            return

        await ctx.reply(
            _("Feeds: {count} active. Query: {query}").format(
                count=len(feeds), query=query or "*"
            )
        )

        for feed in feeds:
            channels = feed.channels or ([feed.channel] if feed.channel else [])
            channels_text = ",".join(channels) if channels else "-"
            min_interval = feed.min_interval_seconds if feed.min_interval_seconds is not None else "-"
            poll_limit = (
                feed.max_items_per_poll
                if feed.max_items_per_poll is not None
                else self.config.feeds.max_items_per_poll
            )
            manual_limit = (
                feed.max_items_per_manual
                if feed.max_items_per_manual is not None
                else self.config.feeds.max_items_per_manual
            )
            mode = "on" if feed.enabled else "off"
            msg = (
                "{name} [{mode}] ch={channels} poll={poll} manual={manual} min={min_interval}s url={url}"
            ).format(
                name=feed.name,
                mode=mode,
                channels=channels_text,
                poll=poll_limit,
                manual=manual_limit,
                min_interval=min_interval,
                url=feed.url,
            )
            await ctx.reply(msg)

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
