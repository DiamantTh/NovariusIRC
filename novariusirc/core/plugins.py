"""Plugin base and manager."""

from __future__ import annotations

import importlib
import logging
from typing import List, Optional

from .auth import AuthManager
from .commands import CommandRegistry
from .config import Config
from .feeds import FeedEngine


class Plugin:
    name: str = "plugin"

    def __init__(
        self,
        config: Config,
        commands: CommandRegistry,
        feeds: FeedEngine,
        auth: AuthManager,
        logger: logging.Logger,
    ):
        self.config = config
        self.commands = commands
        self.feeds = feeds
        self.auth = auth
        self.logger = logger.getChild(self.name)
        self.client = None

    def set_client(self, client: object) -> None:
        self.client = client

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def on_message(self, nick: str, channel: str, message: str) -> None:
        return None


class PluginManager:
    def __init__(
        self,
        config: Config,
        commands: CommandRegistry,
        feeds: FeedEngine,
        auth: AuthManager,
        logger: logging.Logger,
    ):
        self.config = config
        self.commands = commands
        self.feeds = feeds
        self.auth = auth
        self.logger = logger.getChild("plugins")
        self.plugins: List[Plugin] = []
        self.client: Optional[object] = None

    def set_client(self, client: object) -> None:
        self.client = client
        for plugin in self.plugins:
            plugin.set_client(client)

    def load_builtin(self) -> None:
        builtin = ["moderation", "rss_announcer"]
        for name in builtin:
            try:
                module = importlib.import_module(f"novariusirc.modules.{name}")
                plugin_cls = getattr(module, "Plugin")
                plugin: Plugin = plugin_cls(self.config, self.commands, self.feeds, self.auth, self.logger)
                if self.client:
                    plugin.set_client(self.client)
                self.plugins.append(plugin)
                self.logger.info("Loaded plugin %s", name)
            except Exception as exc:
                self.logger.error("Failed to load plugin %s: %s", name, exc)

    async def start(self) -> None:
        for plugin in self.plugins:
            await plugin.start()

    async def stop(self) -> None:
        for plugin in self.plugins:
            await plugin.stop()

    async def on_message(self, nick: str, channel: str, message: str) -> None:
        for plugin in self.plugins:
            try:
                await plugin.on_message(nick, channel, message)
            except Exception as exc:
                self.logger.error("Plugin %s failed while handling message: %s", plugin.name, exc)
