"""Plugin system for NovariusIRC.

Allows loading external Python plugins from plugins/ directory.
Plugins can define hooks for IRC events and custom commands.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
from abc import ABC
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .auth import AuthManager
from .commands import CommandRegistry
from .config import Config
from .feeds import FeedEngine


@dataclass
class CommandContext:
    """Context passed to command/hook handlers."""

    nick: str
    channel: str
    message: str
    role: str  # "user", "admin", "owner"
    irc: Any  # IRCClient reference


class command:
    """Decorator for plugin commands."""

    def __init__(self, role: str = "user", aliases: Optional[List[str]] = None):
        """Initialize command decorator.

        Args:
            role: Minimum role required ("user", "admin", "owner")
            aliases: Alternative command names
        """
        self.role = role
        self.aliases = aliases or []

    def __call__(self, func: Callable) -> Callable:
        """Mark function as a command."""
        func._is_command = True
        func._command_role = self.role
        func._command_aliases = self.aliases
        func._command_name = func.__name__.replace("cmd_", "")
        return func


class BasePlugin(ABC):
    """Base class for NovariusIRC plugins.

    Subclass and define hook methods (on_message, on_join, etc.)
    and commands (cmd_* methods with @command decorator).
    """

    name: str = "plugin"
    version: str = "1.0"
    description: str = "A NovariusIRC plugin"

    async def on_load(self) -> None:
        """Called when plugin is loaded."""
        pass

    async def on_unload(self) -> None:
        """Called when plugin is unloaded."""
        pass

    async def on_message(self, ctx: CommandContext) -> None:
        """Called on every IRC PRIVMSG."""
        pass

    async def on_join(self, ctx: CommandContext) -> None:
        """Called when user joins channel."""
        pass

    async def on_part(self, ctx: CommandContext) -> None:
        """Called when user leaves channel."""
        pass

    async def on_quit(self, ctx: CommandContext) -> None:
        """Called when user quits IRC."""
        pass

    def get_commands(self) -> Dict[str, Dict[str, Any]]:
        """Return dict of available commands."""
        commands = {}

        for attr_name in dir(self):
            if attr_name.startswith("_"):
                continue

            attr = getattr(self, attr_name)
            if not callable(attr):
                continue

            if not getattr(attr, "_is_command", False):
                continue

            cmd_name = getattr(attr, "_command_name", attr_name.replace("cmd_", ""))
            commands[cmd_name] = {
                "handler": attr,
                "role": getattr(attr, "_command_role", "user"),
                "aliases": getattr(attr, "_command_aliases", []),
                "help": attr.__doc__ or "No description",
            }

        return commands


class Plugin:
    """Legacy plugin class for backward compatibility."""

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
    """Manages legacy Plugin instances and new BasePlugin plugins."""

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
        self.loader: Optional[PluginLoader] = None
        self.client: Optional[object] = None

    def set_client(self, client: object) -> None:
        self.client = client
        for plugin in self.plugins:
            plugin.set_client(client)

    def load_builtin(self) -> None:
        """Load built-in plugins from novariusirc.modules."""
        builtin = self.config.modules.enabled
        for name in builtin:
            try:
                module = importlib.import_module(f"novariusirc.modules.{name}")
                plugin_cls = getattr(module, "Plugin")
                plugin: Plugin = plugin_cls(
                    self.config, self.commands, self.feeds, self.auth, self.logger
                )
                if self.client:
                    plugin.set_client(self.client)
                self.plugins.append(plugin)
                self.logger.info("Loaded plugin %s", name)
            except Exception as exc:
                self.logger.error("Failed to load plugin %s: %s", name, exc)

    async def load_plugins(self, plugin_dir: Optional[Path] = None) -> None:
        """Load external plugins from directory.

        Args:
            plugin_dir: Directory containing plugins (default: ./plugins)
        """
        self.loader = PluginLoader(plugin_dir)
        await self.loader.load_all()

    async def start(self) -> None:
        """Start all plugins."""
        for plugin in self.plugins:
            await plugin.start()

    async def stop(self) -> None:
        """Stop all plugins."""
        for plugin in self.plugins:
            await plugin.stop()

    def _role_for_hostmask(self, nick: str, hostmask: str) -> str:
        """Get highest role for user based on hostmask."""
        roles = self.auth.roles_for_hostmask(nick, hostmask)
        if "owner" in roles:
            return "owner"
        if "admin" in roles:
            return "admin"
        return "user"

    async def on_message(self, nick: str, channel: str, message: str, hostmask: str = "") -> None:
        """Trigger on_message hook for all plugins.
        
        Args:
            nick: Sender nickname
            channel: Target channel or nick (for PM)
            message: Message content
            hostmask: Full hostmask nick!user@host (if available)
        """
        for plugin in self.plugins:
            try:
                await plugin.on_message(nick, channel, message)
            except Exception as exc:
                self.logger.error("Plugin %s failed while handling message: %s", plugin.name, exc)

        if self.loader:
            hostmask = hostmask or f"{nick}!unknown@unknown"
            ctx = CommandContext(
                nick=nick,
                channel=channel,
                message=message,
                role=self._role_for_hostmask(nick, hostmask),
                irc=self.client,
            )
            await self.loader.trigger_hook("on_message", ctx)

    async def on_join(self, nick: str, channel: str, hostmask: str = "") -> None:
        if self.loader:
            hostmask = hostmask or f"{nick}!unknown@unknown"
            ctx = CommandContext(
                nick=nick,
                channel=channel,
                message="",
                role=self._role_for_hostmask(nick, hostmask),
                irc=self.client,
            )
            await self.loader.trigger_hook("on_join", ctx)

    async def on_part(self, nick: str, channel: str, message: str, hostmask: str = "") -> None:
        if self.loader:
            hostmask = hostmask or f"{nick}!unknown@unknown"
            ctx = CommandContext(
                nick=nick,
                channel=channel,
                message=message,
                role=self._role_for_hostmask(nick, hostmask),
                irc=self.client,
            )
            await self.loader.trigger_hook("on_part", ctx)

    async def on_quit(self, nick: str, message: str, hostmask: str = "") -> None:
        if self.loader:
            hostmask = hostmask or f"{nick}!unknown@unknown"
            ctx = CommandContext(
                nick=nick,
                channel="",
                message=message,
                role=self._role_for_hostmask(nick, hostmask),
                irc=self.client,
            )
            await self.loader.trigger_hook("on_quit", ctx)

    async def on_nick_change(self, old_nick: str, new_nick: str) -> None:
        if self.loader:
            ctx = CommandContext(
                nick=new_nick,
                channel="",
                message=f"{old_nick}->{new_nick}",
                role=self._role_for_nick(new_nick),
                irc=self.client,
            )
            await self.loader.trigger_hook("on_nick_change", ctx)


class PluginLoader:
    """Loads and manages BasePlugin plugins from plugins/ directory."""

    def __init__(self, plugin_dir: Optional[Path] = None):
        """Initialize plugin loader.

        Args:
            plugin_dir: Directory containing plugins (default: ./plugins)
        """
        self.plugin_dir = plugin_dir or Path.cwd() / "plugins"
        self.plugins: Dict[str, BasePlugin] = {}
        self.hooks: Dict[str, List[Callable]] = {
            "on_message": [],
            "on_join": [],
            "on_part": [],
            "on_quit": [],
            "on_nick_change": [],
        }
        self.commands: Dict[str, Dict[str, Any]] = {}
        self.logger = logging.getLogger("plugins.loader")

    async def load_all(self) -> int:
        """Load all plugins from plugin directory.

        Returns:
            Number of plugins loaded
        """
        if not self.plugin_dir.exists():
            self.logger.debug(f"Plugin directory not found: {self.plugin_dir}")
            return 0

        loaded = 0
        for plugin_file in sorted(self.plugin_dir.glob("*.py")):
            if plugin_file.name.startswith("_"):
                continue

            try:
                await self.load(plugin_file)
                loaded += 1
            except Exception as e:
                self.logger.error(f"Failed to load plugin {plugin_file.name}: {e}")

        if loaded > 0:
            self.logger.info(f"Loaded {loaded} plugins from {self.plugin_dir}")
        return loaded

    async def load(self, plugin_path: Path) -> None:
        """Load a single plugin.

        Args:
            plugin_path: Path to plugin .py file
        """
        if not plugin_path.exists():
            raise FileNotFoundError(f"Plugin not found: {plugin_path}")

        # Import module
        spec = importlib.util.spec_from_file_location(plugin_path.stem, plugin_path)
        if not spec or not spec.loader:
            raise RuntimeError(f"Cannot load module spec: {plugin_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find BasePlugin subclasses
        for name, obj in inspect.getmembers(module):
            if not inspect.isclass(obj):
                continue

            if not issubclass(obj, BasePlugin) or obj is BasePlugin:
                continue

            # Instantiate and register plugin
            plugin = obj()
            self.plugins[plugin.name] = plugin

            # Register hooks
            for hook_name in self.hooks.keys():
                if hasattr(plugin, hook_name):
                    method = getattr(plugin, hook_name)
                    self.hooks[hook_name].append(method)

            # Register commands
            for cmd_name, cmd_info in plugin.get_commands().items():
                self.commands[cmd_name] = cmd_info

            self.logger.info(f"Loaded plugin: {plugin.name} v{plugin.version}")
            await plugin.on_load()

    async def unload(self, plugin_name: str) -> None:
        """Unload a plugin.

        Args:
            plugin_name: Name of plugin to unload
        """
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin not found: {plugin_name}")

        plugin = self.plugins[plugin_name]
        await plugin.on_unload()

        # Remove hooks
        for hook_list in self.hooks.values():
            hook_list[:] = [h for h in hook_list if h.__self__ is not plugin]

        # Remove commands
        for cmd_name in list(self.commands.keys()):
            if self.commands[cmd_name]["handler"].__self__ is plugin:
                del self.commands[cmd_name]

        del self.plugins[plugin_name]
        self.logger.info(f"Unloaded plugin: {plugin_name}")

    async def trigger_hook(self, hook_name: str, ctx: CommandContext) -> None:
        """Trigger a hook for all registered plugins.

        Args:
            hook_name: Name of hook (e.g., "on_message")
            ctx: Command context
        """
        if hook_name not in self.hooks:
            return

        for handler in self.hooks[hook_name]:
            try:
                await handler(ctx)
            except Exception as e:
                self.logger.error(f"Plugin hook error in {hook_name}: {e}", exc_info=True)

    def get_command(self, cmd_name: str) -> Optional[Dict[str, Any]]:
        """Get command info by name.

        Args:
            cmd_name: Command name

        Returns:
            Command info dict or None if not found
        """
        # Check direct match
        if cmd_name in self.commands:
            return self.commands[cmd_name]

        # Check aliases
        for cmd_info in self.commands.values():
            if cmd_name in cmd_info.get("aliases", []):
                return cmd_info

        return None

    def list_commands(self, role: str = "user") -> Dict[str, str]:
        """List all available commands for a role.

        Args:
            role: User role ("user", "admin", "owner")

        Returns:
            Dict of command_name -> help_text
        """
        commands = {}

        role_hierarchy = {"user": 0, "admin": 1, "owner": 2}
        user_level = role_hierarchy.get(role, 0)

        for cmd_name, cmd_info in self.commands.items():
            required_level = role_hierarchy.get(cmd_info["role"], 0)
            if user_level >= required_level:
                commands[cmd_name] = cmd_info["help"]

        return commands
