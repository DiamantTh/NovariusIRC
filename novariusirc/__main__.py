"""CLI entry point for NovariusIRC."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from novariusirc import __version__
from novariusirc.core.auth import AuthManager
from novariusirc.core.client import IRCClient
from novariusirc.core.commands import CommandContext, CommandRegistry
from novariusirc.core.config import Config, load_config
from novariusirc.core.feeds import FeedEngine
from novariusirc.core.i18n import init_i18n
from novariusirc.core.i18n import gettext_lazy as _
from novariusirc.core.logging import setup_logging
from novariusirc.core.moderation import ModerationManager
from novariusirc.core.plugins import PluginManager
from novariusirc.core.workers import WorkerPool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NovariusIRC bot")
    parser.add_argument("-c", "--config", type=Path, default=Path("./config.toml"), help="Path to config.toml or 'env'")
    parser.add_argument("-s", "--channel-stats", action="store_true", help="Don't background; display channel stats every 10 seconds")
    parser.add_argument("-t", "--terminal-dcc", action="store_true", help="Don't background; use terminal to simulate DCC chat")
    parser.add_argument("-f", "--foreground", action="store_true", help="Don't background; stay in foreground")
    parser.add_argument("-V", "--version", action="version", version=f"NovariusIRC {__version__}", help="Show version and exit")
    return parser.parse_args()


def configure_event_loop() -> None:
    try:
        import uvloop  # type: ignore

        uvloop.install()
    except Exception:
        return


def register_builtin_commands(commands: CommandRegistry, config: Config, auth: AuthManager, start_time: float) -> None:
    async def ping(ctx: CommandContext, args: list[str]) -> None:
        await ctx.reply(_("pong"))

    async def uptime(ctx: CommandContext, args: list[str]) -> None:
        seconds = int(time.monotonic() - start_time)
        await ctx.reply(_("uptime: {seconds}s").format(seconds=seconds))

    async def version(ctx: CommandContext, args: list[str]) -> None:
        await ctx.reply(f"NovariusIRC {__version__}")

    async def help_cmd(ctx: CommandContext, args: list[str]) -> None:
        lines = [_("Commands ({prefix}):").format(prefix=config.bot.prefix)]
        for cmd in commands.list_commands():
            lines.append(f"{cmd.name} - {cmd.help_text}")
        await ctx.reply(" | ".join(lines))


    commands.register("ping", ping, help_text="Health check")
    commands.register("uptime", uptime, help_text="Show bot uptime")
    commands.register("version", version, help_text="Show bot version")
    commands.register("help", help_cmd, help_text="Show available commands")


async def async_main() -> None:
    args = parse_args()
    config = load_config(args.config)
    _ = init_i18n(config.bot.language)  # noqa: F841
    logger = setup_logging(config.logging, config.paths)
    
    # Log startup mode
    if args.channel_stats:
        logger.info("Starting in channel-stats mode (foreground)")
    elif args.terminal_dcc:
        logger.info("Starting in terminal-DCC mode (foreground)")
    elif args.foreground:
        logger.info("Starting in foreground mode")
    
    auth = AuthManager(config.auth, config.roles, logger)
    commands = CommandRegistry(prefix=config.bot.prefix, rate_limit_seconds=config.commands.rate_limit_seconds)
    start_time = time.monotonic()
    register_builtin_commands(commands, config, auth, start_time)

    feeds = FeedEngine(config.feeds, logger, data_root=Path(config.paths.data_root))
    workers = WorkerPool(config.workers, logger)
    plugins = PluginManager(config, commands, feeds, auth, logger)
    moderation = ModerationManager(config.moderation.model_dump())

    client = IRCClient(config, commands, auth, plugins, moderation, logger)
    plugins.set_client(client)
    plugins.load_builtin()
    if config.plugins.enabled:
        await plugins.load_plugins(Path(config.plugins.directory))
    await plugins.start()
    await feeds.start()

    await client.run()
    await plugins.stop()
    await feeds.stop()
    await workers.shutdown()


def main() -> None:
    configure_event_loop()
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
