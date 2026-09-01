"""Built-in and explicitly enabled external plugin support."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import logging
import re
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from .auth import AuthManager
from .commands import CommandContext, CommandRegistry, command
from .config import Config
from .feeds import FeedEngine
from .tasks import TaskSupervisor

PLUGIN_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
HOOK_NAMES = (
    "on_message",
    "on_action",
    "on_notice",
    "on_join",
    "on_part",
    "on_quit",
    "on_nick_change",
    "on_kick",
    "on_mode",
    "on_topic",
    "on_account",
    "on_away",
    "on_chghost",
    "on_invite",
    "on_tagmsg",
)

__all__ = ["BasePlugin", "CommandContext", "Plugin", "PluginManager", "command"]


class BasePlugin:
    """Base class for external plugins loaded from the configured directory."""

    name = "plugin"
    version = "1.0"
    description = "A NovariusIRC plugin"

    config: Config
    client: object | None
    logger: logging.Logger

    async def on_load(self) -> None:
        """Run after services and commands have been registered."""

    async def on_unload(self) -> None:
        """Run before the plugin is removed."""

    async def on_message(self, ctx: CommandContext) -> None:
        """Handle an IRC PRIVMSG that was not consumed by a command."""

    async def on_action(self, ctx: CommandContext) -> None:
        """Handle a CTCP ACTION."""

    async def on_notice(self, ctx: CommandContext) -> None:
        """Handle an IRC NOTICE."""

    async def on_join(self, ctx: CommandContext) -> None:
        """Handle an IRC JOIN."""

    async def on_part(self, ctx: CommandContext) -> None:
        """Handle an IRC PART."""

    async def on_quit(self, ctx: CommandContext) -> None:
        """Handle an IRC QUIT."""

    async def on_nick_change(self, ctx: CommandContext) -> None:
        """Handle an IRC NICK change."""

    async def on_kick(self, ctx: CommandContext) -> None:
        """Handle an IRC KICK."""

    async def on_mode(self, ctx: CommandContext) -> None:
        """Handle an IRC channel MODE change."""

    async def on_topic(self, ctx: CommandContext) -> None:
        """Handle an IRC TOPIC change."""

    async def on_account(self, ctx: CommandContext) -> None:
        """Handle an IRCv3 ACCOUNT change."""

    async def on_away(self, ctx: CommandContext) -> None:
        """Handle an IRCv3 AWAY notification."""

    async def on_chghost(self, ctx: CommandContext) -> None:
        """Handle an IRCv3 CHGHOST notification."""

    async def on_invite(self, ctx: CommandContext) -> None:
        """Handle an IRC INVITE or invite-notify event."""

    async def on_tagmsg(self, ctx: CommandContext) -> None:
        """Handle an IRCv3 TAGMSG event."""

    def _bind_services(
        self,
        config: Config,
        client: object | None,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.client = client
        self.logger = logger.getChild(self.name)

    def get_commands(self) -> list[tuple[Callable[..., Any], dict[str, Any]]]:
        commands: list[tuple[Callable[..., Any], dict[str, Any]]] = []
        for attribute_name in dir(self):
            if attribute_name.startswith("_"):
                continue
            handler = getattr(self, attribute_name)
            metadata = getattr(handler, "__novarius_command__", None)
            if callable(handler) and metadata:
                commands.append((handler, dict(metadata)))
        return commands


class Plugin:
    """Compatibility base class for built-in modules."""

    name = "plugin"

    def __init__(
        self,
        config: Config,
        commands: CommandRegistry,
        feeds: FeedEngine,
        auth: AuthManager,
        logger: logging.Logger,
        tasks: TaskSupervisor,
    ):
        self.config = config
        self.commands = commands
        self.feeds = feeds
        self.auth = auth
        self.logger = logger.getChild(self.name)
        self.tasks = tasks
        self.client: object | None = None

    def set_client(self, client: object) -> None:
        self.client = client

    def create_task(self, coroutine, *, name: str | None = None):
        """Register background work that belongs to this built-in module."""
        return self.tasks.create_task(self.name, coroutine, name=name)

    async def start(self) -> None:
        """Start the built-in module."""

    async def stop(self) -> None:
        """Stop the built-in module."""

    async def on_message(self, nick: str, channel: str, message: str) -> None:
        """Handle an unconsumed message."""


class PluginLoader:
    """Load named external plugins and register them with core services."""

    def __init__(
        self,
        plugin_dir: Path,
        enabled_plugins: list[str],
        commands: CommandRegistry,
        config: Config,
        logger: logging.Logger,
        client: object | None,
    ):
        self.plugin_dir = plugin_dir
        self.enabled_plugins = enabled_plugins
        self.commands = commands
        self.config = config
        self.logger = logger.getChild("loader")
        self.client = client
        self.plugins: dict[str, BasePlugin] = {}
        self.hooks: dict[str, list[Callable[[CommandContext], Any]]] = {
            hook_name: [] for hook_name in HOOK_NAMES
        }
        self._owners: dict[str, str] = {}
        self._module_names: dict[str, str] = {}

    def set_client(self, client: object) -> None:
        self.client = client
        for plugin in self.plugins.values():
            plugin.client = client

    def _resolve_plugin(self, configured_name: str) -> tuple[Path, bool]:
        if not PLUGIN_NAME_RE.fullmatch(configured_name):
            raise ValueError(f"Invalid plugin name: {configured_name!r}")

        file_path = self.plugin_dir / f"{configured_name}.py"
        if file_path.is_file():
            return file_path, False

        package_init = self.plugin_dir / configured_name / "__init__.py"
        if package_init.is_file():
            return package_init, True

        raise FileNotFoundError(
            f"Configured plugin {configured_name!r} was not found in {self.plugin_dir}"
        )

    @staticmethod
    def _plugin_class(module: ModuleType) -> type[BasePlugin]:
        candidates = [
            value
            for _, value in inspect.getmembers(module, inspect.isclass)
            if issubclass(value, BasePlugin)
            and value is not BasePlugin
            and value.__module__ == module.__name__
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                "External plugin modules must define exactly one BasePlugin subclass"
            )
        return candidates[0]

    async def load_all(self) -> int:
        if not self.enabled_plugins:
            self.logger.info("No external plugins configured")
            return 0
        if not self.plugin_dir.is_dir():
            raise FileNotFoundError(f"Plugin directory not found: {self.plugin_dir}")

        loaded = 0
        failed: list[str] = []
        for configured_name in self.enabled_plugins:
            try:
                await self.load(configured_name)
                loaded += 1
            except Exception:
                failed.append(configured_name)
                self.logger.exception("Failed to load plugin %s", configured_name)
        if failed:
            await self.unload_all()
            names = ", ".join(failed)
            raise RuntimeError(f"Failed to load configured plugins: {names}")
        self.logger.info("Loaded %s external plugin(s)", loaded)
        return loaded

    async def load(self, configured_name: str) -> None:
        plugin_path, is_package = self._resolve_plugin(configured_name)
        module_name = f"novariusirc_external_{configured_name}"
        search_locations = [str(plugin_path.parent)] if is_package else None
        spec = importlib.util.spec_from_file_location(
            module_name,
            plugin_path,
            submodule_search_locations=search_locations,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot create module spec for {plugin_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        owner: str | None = None
        try:
            spec.loader.exec_module(module)
            plugin_class = self._plugin_class(module)
            plugin = plugin_class()
            if not PLUGIN_NAME_RE.fullmatch(plugin.name):
                raise ValueError(f"Invalid plugin class name: {plugin.name!r}")
            if plugin.name in self.plugins:
                raise ValueError(f"Plugin name already loaded: {plugin.name}")

            owner = f"external:{plugin.name}"
            plugin._bind_services(self.config, self.client, self.logger)
            for handler, metadata in plugin.get_commands():
                self.commands.register(
                    metadata["name"],
                    handler,
                    roles=metadata["roles"],
                    help_text=metadata["help_text"],
                    aliases=metadata["aliases"],
                    owner=owner,
                )

            await plugin.on_load()
            self.plugins[plugin.name] = plugin
            self._owners[plugin.name] = owner
            self._module_names[plugin.name] = module_name
            for hook_name in HOOK_NAMES:
                implementation = getattr(type(plugin), hook_name, None)
                if implementation is not getattr(BasePlugin, hook_name):
                    self.hooks[hook_name].append(getattr(plugin, hook_name))
            self.logger.info("Loaded plugin %s v%s", plugin.name, plugin.version)
        except Exception:
            if owner:
                self.commands.unregister_owner(owner)
            sys.modules.pop(module_name, None)
            raise

    async def unload(self, plugin_name: str) -> None:
        plugin = self.plugins.get(plugin_name)
        if plugin is None:
            raise ValueError(f"Plugin not loaded: {plugin_name}")

        try:
            await plugin.on_unload()
        except Exception:
            self.logger.exception("Plugin %s failed during unload", plugin_name)
        finally:
            for hook_list in self.hooks.values():
                hook_list[:] = [
                    handler
                    for handler in hook_list
                    if getattr(handler, "__self__", None) is not plugin
                ]
            self.commands.unregister_owner(self._owners.pop(plugin_name))
            sys.modules.pop(self._module_names.pop(plugin_name), None)
            del self.plugins[plugin_name]
            self.logger.info("Unloaded plugin %s", plugin_name)

    async def unload_all(self) -> None:
        for plugin_name in reversed(tuple(self.plugins)):
            await self.unload(plugin_name)

    async def trigger_hook(self, hook_name: str, ctx: CommandContext) -> None:
        for handler in self.hooks.get(hook_name, ()):
            try:
                result = handler(ctx)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                self.logger.exception("Plugin hook %s failed", hook_name)


class PluginManager:
    """Coordinate built-in modules and external plugins."""

    def __init__(
        self,
        config: Config,
        commands: CommandRegistry,
        feeds: FeedEngine,
        auth: AuthManager,
        logger: logging.Logger,
        tasks: TaskSupervisor | None = None,
    ):
        self.config = config
        self.commands = commands
        self.feeds = feeds
        self.auth = auth
        self.logger = logger.getChild("plugins")
        self.tasks = tasks or TaskSupervisor(self.logger)
        self.plugins: list[Plugin] = []
        self._started_modules: list[Plugin] = []
        self.loader: PluginLoader | None = None
        self.client: object | None = None

    def set_client(self, client: object) -> None:
        self.client = client
        for plugin in self.plugins:
            plugin.set_client(client)
        if self.loader:
            self.loader.set_client(client)

    @property
    def active_builtin_modules(self) -> tuple[str, ...]:
        return tuple(plugin.name for plugin in self._started_modules)

    def load_builtin(self) -> None:
        failed: list[str] = []
        for name in self.config.modules.enabled:
            try:
                module = importlib.import_module(f"novariusirc.modules.{name}")
                plugin_class = module.Plugin
                plugin = plugin_class(
                    self.config,
                    self.commands,
                    self.feeds,
                    self.auth,
                    self.logger,
                    self.tasks,
                )
                if self.client:
                    plugin.set_client(self.client)
                self.plugins.append(plugin)
                self.logger.info("Loaded built-in module %s", name)
            except Exception:
                failed.append(name)
                self.logger.exception("Failed to load built-in module %s", name)
        if failed:
            raise RuntimeError(f"Failed to load built-in modules: {', '.join(failed)}")

    async def load_plugins(self, plugin_dir: Path | None = None) -> None:
        directory = plugin_dir or Path.cwd() / self.config.plugins.directory
        self.loader = PluginLoader(
            directory,
            self.config.plugins.load,
            self.commands,
            self.config,
            self.logger,
            self.client,
        )
        await self.loader.load_all()

    async def start_builtin_modules(self) -> None:
        """Start built-in modules in order and roll back a partial start."""
        for plugin in self.plugins:
            try:
                await asyncio.wait_for(
                    plugin.start(),
                    timeout=self.config.lifecycle.module_start_timeout_seconds,
                )
            except TimeoutError as exc:
                self.logger.error("Built-in module %s timed out during start", plugin.name)
                await self._stop_builtin_module(plugin)
                await self.stop_builtin_modules()
                raise RuntimeError(
                    f"Built-in module {plugin.name!r} timed out during start"
                ) from exc
            except Exception:
                self.logger.exception("Built-in module %s failed during start", plugin.name)
                await self._stop_builtin_module(plugin)
                await self.stop_builtin_modules()
                raise
            self._started_modules.append(plugin)

    async def _stop_builtin_module(self, plugin: Plugin) -> None:
        await self.tasks.cancel_owner(
            plugin.name,
            timeout=self.config.lifecycle.module_stop_timeout_seconds,
        )
        try:
            await asyncio.wait_for(
                plugin.stop(),
                timeout=self.config.lifecycle.module_stop_timeout_seconds,
            )
        except TimeoutError:
            self.logger.error("Built-in module %s timed out during stop", plugin.name)
        except Exception:
            self.logger.exception("Built-in module %s failed during stop", plugin.name)

    async def stop_builtin_modules(self) -> None:
        """Stop every started built-in module without skipping later cleanup."""
        for plugin in reversed(self._started_modules):
            await self._stop_builtin_module(plugin)
        self._started_modules.clear()

    async def start(self) -> None:
        """Compatibility wrapper for the built-in module lifecycle."""
        await self.start_builtin_modules()

    async def stop(self) -> None:
        try:
            if self.loader:
                await self.loader.unload_all()
        finally:
            await self.stop_builtin_modules()

    def _context(
        self,
        nick: str,
        channel: str | None,
        message: str,
        hostmask: str,
        tags: dict[str, str | None] | None = None,
        account: str | None = None,
        event: str = "PRIVMSG",
        server_time: datetime | None = None,
        metadata: dict[str, object] | None = None,
    ) -> CommandContext:
        resolved_hostmask = hostmask or f"{nick}!unknown@unknown"
        return CommandContext(
            nick=nick,
            hostmask=resolved_hostmask,
            channel=channel,
            message=message,
            config=self.config,
            client=self.client,
            logger=self.logger,
            roles=self.auth.roles_for_identity(
                nick,
                resolved_hostmask,
                account=account,
                certfp=self.auth.certfp_from_tags(dict(tags or {})),
            ),
            tags=dict(tags or {}),
            account=account,
            event=event,
            server_time=server_time,
            metadata=dict(metadata or {}),
        )

    async def on_message(
        self,
        nick: str,
        channel: str,
        message: str,
        hostmask: str = "",
        tags: dict[str, str | None] | None = None,
        account: str | None = None,
        server_time: datetime | None = None,
    ) -> None:
        for plugin in self.plugins:
            try:
                await plugin.on_message(nick, channel, message)
            except Exception:
                self.logger.exception("Built-in plugin %s failed", plugin.name)
        if self.loader:
            await self.loader.trigger_hook(
                "on_message",
                self._context(
                    nick,
                    channel,
                    message,
                    hostmask,
                    tags,
                    account,
                    server_time=server_time,
                ),
            )

    async def on_join(
        self,
        nick: str,
        channel: str,
        hostmask: str = "",
        *,
        account: str | None = None,
        realname: str | None = None,
        tags: dict[str, str | None] | None = None,
        server_time: datetime | None = None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_join",
                self._context(
                    nick,
                    channel,
                    "",
                    hostmask,
                    tags,
                    account,
                    event="JOIN",
                    server_time=server_time,
                    metadata={"realname": realname},
                ),
            )

    async def on_action(
        self,
        nick: str,
        channel: str | None,
        message: str,
        hostmask: str,
        account: str | None,
        tags: dict[str, str | None],
        server_time: datetime | None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_action",
                self._context(
                    nick,
                    channel,
                    message,
                    hostmask,
                    tags,
                    account,
                    event="ACTION",
                    server_time=server_time,
                ),
            )

    async def on_notice(
        self,
        nick: str,
        channel: str | None,
        message: str,
        hostmask: str,
        account: str | None,
        tags: dict[str, str | None],
        server_time: datetime | None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_notice",
                self._context(
                    nick,
                    channel,
                    message,
                    hostmask,
                    tags,
                    account,
                    event="NOTICE",
                    server_time=server_time,
                ),
            )

    async def on_part(
        self,
        nick: str,
        channel: str,
        message: str,
        hostmask: str = "",
        *,
        account: str | None = None,
        tags: dict[str, str | None] | None = None,
        server_time: datetime | None = None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_part",
                self._context(
                    nick,
                    channel,
                    message,
                    hostmask,
                    tags,
                    account,
                    event="PART",
                    server_time=server_time,
                ),
            )

    async def on_quit(
        self,
        nick: str,
        message: str,
        hostmask: str = "",
        *,
        account: str | None = None,
        tags: dict[str, str | None] | None = None,
        server_time: datetime | None = None,
        channels: list[str] | None = None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_quit",
                self._context(
                    nick,
                    None,
                    message,
                    hostmask,
                    tags,
                    account,
                    event="QUIT",
                    server_time=server_time,
                    metadata={"channels": list(channels or [])},
                ),
            )

    async def on_nick_change(
        self,
        old_nick: str,
        new_nick: str,
        hostmask: str = "",
        *,
        account: str | None = None,
        tags: dict[str, str | None] | None = None,
        server_time: datetime | None = None,
        channels: list[str] | None = None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_nick_change",
                self._context(
                    new_nick,
                    None,
                    f"{old_nick}->{new_nick}",
                    hostmask,
                    tags,
                    account,
                    event="NICK",
                    server_time=server_time,
                    metadata={
                        "old_nick": old_nick,
                        "new_nick": new_nick,
                        "channels": list(channels or []),
                    },
                ),
            )

    async def on_account(
        self,
        nick: str,
        account: str | None,
        hostmask: str,
        tags: dict[str, str | None],
        server_time: datetime | None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_account",
                self._context(
                    nick,
                    None,
                    account or "*",
                    hostmask,
                    tags,
                    account,
                    event="ACCOUNT",
                    server_time=server_time,
                ),
            )

    async def on_kick(
        self,
        nick: str,
        channel: str,
        target: str,
        message: str,
        hostmask: str,
        account: str | None,
        tags: dict[str, str | None],
        server_time: datetime | None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_kick",
                self._context(
                    nick,
                    channel,
                    message,
                    hostmask,
                    tags,
                    account,
                    event="KICK",
                    server_time=server_time,
                    metadata={"target": target},
                ),
            )

    async def on_mode(
        self,
        nick: str,
        channel: str,
        modes: str,
        arguments: list[str],
        hostmask: str,
        account: str | None,
        tags: dict[str, str | None],
        server_time: datetime | None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_mode",
                self._context(
                    nick,
                    channel,
                    modes,
                    hostmask,
                    tags,
                    account,
                    event="MODE",
                    server_time=server_time,
                    metadata={"arguments": list(arguments)},
                ),
            )

    async def on_topic(
        self,
        nick: str,
        channel: str,
        topic: str,
        hostmask: str,
        account: str | None,
        tags: dict[str, str | None],
        server_time: datetime | None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_topic",
                self._context(
                    nick,
                    channel,
                    topic,
                    hostmask,
                    tags,
                    account,
                    event="TOPIC",
                    server_time=server_time,
                ),
            )

    async def on_away(
        self,
        nick: str,
        away_message: str | None,
        hostmask: str,
        account: str | None,
        tags: dict[str, str | None],
        server_time: datetime | None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_away",
                self._context(
                    nick,
                    None,
                    away_message or "",
                    hostmask,
                    tags,
                    account,
                    event="AWAY",
                    server_time=server_time,
                    metadata={"away": away_message is not None},
                ),
            )

    async def on_chghost(
        self,
        nick: str,
        hostmask: str,
        old_hostmask: str,
        account: str | None,
        tags: dict[str, str | None],
        server_time: datetime | None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_chghost",
                self._context(
                    nick,
                    None,
                    hostmask,
                    hostmask,
                    tags,
                    account,
                    event="CHGHOST",
                    server_time=server_time,
                    metadata={"old_hostmask": old_hostmask},
                ),
            )

    async def on_invite(
        self,
        nick: str,
        target: str,
        channel: str,
        hostmask: str,
        account: str | None,
        tags: dict[str, str | None],
        server_time: datetime | None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_invite",
                self._context(
                    nick,
                    channel,
                    target,
                    hostmask,
                    tags,
                    account,
                    event="INVITE",
                    server_time=server_time,
                    metadata={"target": target},
                ),
            )

    async def on_tagmsg(
        self,
        nick: str,
        target: str,
        channel: str | None,
        hostmask: str,
        account: str | None,
        tags: dict[str, str | None],
        server_time: datetime | None,
    ) -> None:
        if self.loader:
            await self.loader.trigger_hook(
                "on_tagmsg",
                self._context(
                    nick,
                    channel,
                    "",
                    hostmask,
                    tags,
                    account,
                    event="TAGMSG",
                    server_time=server_time,
                    metadata={"target": target},
                ),
            )
