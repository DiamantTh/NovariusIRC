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
from novariusirc.core.i18n import gettext_lazy as _
from novariusirc.core.i18n import init_i18n
from novariusirc.core.logging import setup_logging
from novariusirc.core.moderation import ModerationManager
from novariusirc.core.plugins import PluginManager
from novariusirc.core.workers import WorkerPool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NovariusIRC bot")
    parser.add_argument(
        "config_path",
        nargs="?",
        type=Path,
        help="Path to config.toml (positional alternative to --config)",
    )
    parser.add_argument(
        "-c",
        "--config",
        dest="config_option",
        type=Path,
        help="Path to config.toml or 'env'",
    )
    parser.add_argument(
        "-s",
        "--channel-stats",
        action="store_true",
        help="Reserved; channel statistics mode is not implemented yet",
    )
    parser.add_argument(
        "-t",
        "--terminal-dcc",
        action="store_true",
        help="Reserved; terminal DCC mode is not implemented yet",
    )
    parser.add_argument(
        "-f",
        "--foreground",
        action="store_true",
        help="Don't background; stay in foreground",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"NovariusIRC {__version__}",
        help="Show version and exit",
    )
    args = parser.parse_args()
    if args.channel_stats:
        parser.error("--channel-stats is not implemented yet")
    if args.terminal_dcc:
        parser.error("--terminal-dcc is not implemented yet")
    args.config = args.config_option or args.config_path or Path("./config.toml")
    return args


def configure_event_loop() -> None:
    try:
        import uvloop  # type: ignore

        uvloop.install()
    except ImportError:
        return


def register_builtin_commands(
    commands: CommandRegistry, config: Config, start_time: float
) -> None:
    async def ping(ctx: CommandContext, args: list[str]) -> None:
        await ctx.reply(_("pong"))

    async def uptime(ctx: CommandContext, args: list[str]) -> None:
        seconds = int(time.monotonic() - start_time)
        await ctx.reply(_("uptime: {seconds}s").format(seconds=seconds))

    async def version(ctx: CommandContext, args: list[str]) -> None:
        await ctx.reply(f"NovariusIRC {__version__}")

    async def help_cmd(ctx: CommandContext, args: list[str]) -> None:
        lines = [_("Commands ({prefix}):").format(prefix=config.bot.prefix)]
        for cmd in commands.list_commands(ctx.roles):
            lines.append(f"{cmd.name} - {cmd.help_text}")
        await ctx.reply(" | ".join(lines))

    commands.register("ping", ping, help_text="Health check")
    commands.register("uptime", uptime, help_text="Show bot uptime")
    commands.register("version", version, help_text="Show bot version")
    commands.register("help", help_cmd, help_text="Show available commands")


async def async_main() -> None:
    args = parse_args()
    config = load_config(args.config)
    init_i18n(config.bot.language)
    logger = setup_logging(config.logging, config.paths)

    if args.foreground:
        logger.info("Starting in foreground mode")

    auth = AuthManager(config.auth, config.roles, logger)
    commands = CommandRegistry(
        prefix=config.bot.prefix, rate_limit_seconds=config.commands.rate_limit_seconds
    )
    start_time = time.monotonic()
    register_builtin_commands(commands, config, start_time)

    feeds = FeedEngine(config.feeds, logger, data_root=Path(config.paths.data_root))
    workers = WorkerPool(config.workers, logger)
    plugins = PluginManager(config, commands, feeds, auth, logger)
    moderation = ModerationManager(config.moderation.model_dump())

    client = IRCClient(config, commands, auth, plugins, moderation, logger)
    plugins.set_client(client)
    try:
        plugins.load_builtin()
        if config.plugins.enabled:
            await plugins.load_plugins(Path(config.plugins.directory))
        await plugins.start()
        await feeds.start()
        await client.run()
    finally:
        await client.stop()
        await feeds.stop()
        await plugins.stop()
        await workers.shutdown()


def main() -> None:
    configure_event_loop()
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
