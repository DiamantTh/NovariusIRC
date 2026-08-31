"""CLI entry point for NovariusIRC."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import os
import signal
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
from novariusirc.core.logging import setup_logging, setup_moderation_logging
from novariusirc.core.moderation import ModerationManager
from novariusirc.core.plugins import Plugin, PluginManager
from novariusirc.core.tasks import TaskSupervisor
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
        "--check-config",
        action="store_true",
        help="Validate configuration and built-in modules without connecting to IRC",
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


def check_config(config: Config) -> list[str]:
    """Return operational configuration errors without changing runtime state.

    External plugins deliberately do not take part in this check.  They are not
    part of the core/module lifecycle and must not execute code during a
    configuration-only invocation.
    """
    errors: list[str] = []

    def writable_parent(path: str) -> bool:
        candidate = Path(path)
        while not candidate.exists() and candidate.parent != candidate:
            candidate = candidate.parent
        return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)

    for label, value in (
        ("CertFP certificate", config.auth.certfp_cert_file),
        ("CertFP key", config.auth.certfp_key_file),
        ("feed CA file", config.feeds.tls_ca_file),
        ("feed client certificate", config.feeds.tls_cert_file),
        ("feed client key", config.feeds.tls_key_file),
    ):
        if value and not Path(value).is_file():
            errors.append(f"{label} is not a readable file: {value}")
    if config.feeds.tls_ca_dir and not Path(config.feeds.tls_ca_dir).is_dir():
        errors.append(f"feed CA directory is not a directory: {config.feeds.tls_ca_dir}")

    for label, path in (
        ("log root", config.paths.log_root),
        ("data root", config.paths.data_root),
        ("moderation log directory", str(Path(config.moderation.log_file).parent)),
    ):
        if not writable_parent(path):
            errors.append(f"{label} cannot be created or written: {path}")

    for name in config.modules.enabled:
        try:
            module = importlib.import_module(f"novariusirc.modules.{name}")
            module_class = module.Plugin
            if not isinstance(module_class, type) or not issubclass(module_class, Plugin):
                errors.append(
                    f"Built-in module {name!r} must export a Plugin subclass"
                )
        except Exception as exc:  # noqa: BLE001 - turn import failures into CLI diagnostics
            errors.append(f"Built-in module {name!r} cannot be loaded: {exc}")

    return errors


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


def register_runtime_commands(
    commands: CommandRegistry,
    client: IRCClient,
    modules: PluginManager,
    feeds: FeedEngine,
) -> None:
    """Register commands whose data exists only after core services are built."""

    async def status(ctx: CommandContext, args: list[str]) -> None:
        connection = "connected" if client.is_connected else "disconnected"
        module_names = ", ".join(modules.active_builtin_modules) or "none"
        feed_state = (
            "running"
            if feeds.is_running
            else ("idle" if feeds.config.enabled else "disabled")
        )
        await ctx.reply(
            f"Status: {connection}; network={client.network_name}; "
            f"modules={module_names}; feeds={feed_state}"
        )

    commands.register("status", status, help_text="Show core service status")


async def async_main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.check_config:
        errors = check_config(config)
        if errors:
            for error in errors:
                print(f"Configuration error: {error}", file=sys.stderr)
            raise SystemExit(1)
        print("Configuration check passed.")
        return
    init_i18n(config.bot.language)
    logger = setup_logging(config.logging, config.paths)
    setup_moderation_logging(config.moderation.log_file)

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
    tasks = TaskSupervisor(logger)
    plugins = PluginManager(config, commands, feeds, auth, logger, tasks)
    moderation = ModerationManager(config.moderation.model_dump())

    client = IRCClient(config, commands, auth, plugins, moderation, logger)
    plugins.set_client(client)
    register_runtime_commands(commands, client, plugins, feeds)
    loop = asyncio.get_running_loop()
    handled_signals = (signal.SIGINT, signal.SIGTERM)
    for handled_signal in handled_signals:
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(
                handled_signal,
                lambda current=handled_signal: (
                    logger.info("Received %s; shutting down", current.name),
                    asyncio.create_task(client.stop()),
                ),
            )
    try:
        plugins.load_builtin()
        if config.plugins.enabled:
            await plugins.load_plugins(Path(config.plugins.directory))
        await plugins.start()
        await feeds.start()
        await client.run()
    finally:
        for handled_signal in handled_signals:
            with contextlib.suppress(NotImplementedError):
                loop.remove_signal_handler(handled_signal)
        await client.stop()
        await feeds.stop()
        await plugins.stop()
        await tasks.shutdown(timeout=config.lifecycle.module_stop_timeout_seconds)
        await workers.shutdown()


def main() -> None:
    configure_event_loop()
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI entry points must fail concisely
        print(f"NovariusIRC could not start: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
