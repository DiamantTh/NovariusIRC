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
from novariusirc.core.logging import setup_logging
from novariusirc.core.plugins import PluginManager
from novariusirc.core.workers import WorkerPool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NovariusIRC bot")
    parser.add_argument("--config", type=Path, default=Path("./config.toml"), help="Path to config.toml")
    parser.add_argument("--profile", type=str, default="default", help="Profile name (reserved)")
    return parser.parse_args()


def configure_event_loop() -> None:
    try:
        import uvloop  # type: ignore

        uvloop.install()
    except Exception:
        return


def register_builtin_commands(commands: CommandRegistry, config: Config, auth: AuthManager, start_time: float) -> None:
    async def ping(ctx: CommandContext, args: list[str]) -> None:
        await ctx.reply("pong")

    async def uptime(ctx: CommandContext, args: list[str]) -> None:
        seconds = int(time.monotonic() - start_time)
        await ctx.reply(f"uptime: {seconds}s")

    async def version(ctx: CommandContext, args: list[str]) -> None:
        await ctx.reply(f"NovariusIRC {__version__}")

    async def help_cmd(ctx: CommandContext, args: list[str]) -> None:
        lines = [f"Commands ({config.bot.prefix}):"]
        for cmd in commands.list_commands():
            lines.append(f"{cmd.name} - {cmd.help_text}")
        await ctx.reply(" | ".join(lines))

    async def auth_cmd(ctx: CommandContext, args: list[str]) -> None:
        if not args:
            await ctx.reply("Usage: !auth <totp-code>")
            return
        code = args[0]
        if auth.start_totp_session(ctx.nick, code):
            await ctx.reply("Authentication accepted for elevated commands.")
        else:
            await ctx.reply("Authentication failed.")

    commands.register("ping", ping, help_text="Health check")
    commands.register("uptime", uptime, help_text="Show bot uptime")
    commands.register("version", version, help_text="Show bot version")
    commands.register("help", help_cmd, help_text="Show available commands")
    commands.register("auth", auth_cmd, help_text="Authenticate with TOTP if required")


async def async_main() -> None:
    args = parse_args()
    config = load_config(args.config)
    _ = init_i18n(config.bot.language)  # noqa: F841
    logger = setup_logging(config.logging, config.paths)
    auth = AuthManager(config.auth, config.roles, logger)
    commands = CommandRegistry(prefix=config.bot.prefix)
    start_time = time.monotonic()
    register_builtin_commands(commands, config, auth, start_time)

    feeds = FeedEngine(config.feeds, logger)
    workers = WorkerPool(config.workers, logger)
    plugins = PluginManager(config, commands, feeds, auth, logger)

    client = IRCClient(config, commands, auth, plugins, logger)
    plugins.set_client(client)
    plugins.load_builtin()
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
