"""CLI entry point for NovariusIRC."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import logging
import os
import signal
import sys
import time
from pathlib import Path

from novariusirc.core.auth import AuthManager
from novariusirc.core.client import IRCClient
from novariusirc.core.commands import CommandContext, CommandRegistry
from novariusirc.core.config import Config, load_config
from novariusirc.core.control import (
    LocalCommandClient,
    UnixControlServer,
    dispatch_local_command,
    run_control_command,
)
from novariusirc.core.feeds import FeedEngine
from novariusirc.core.i18n import init_i18n
from novariusirc.core.logging import setup_logging, setup_moderation_logging
from novariusirc.core.moderation import ModerationManager
from novariusirc.core.plugins import Plugin, PluginManager
from novariusirc.core.tasks import TaskSupervisor
from novariusirc.core.workers import WorkerPool
from novariusirc.version import SIMPLE_VERSION, detailed_version


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NovariusIRC bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
        "--status",
        "--channel-stats",
        dest="status",
        action="store_true",
        help="Show configured core status without connecting to IRC",
    )
    parser.add_argument(
        "-t",
        "--terminal-dcc",
        action="store_true",
        help="Run a local terminal control console alongside the bot",
    )
    parser.add_argument(
        "--ctl",
        metavar="COMMAND",
        help="Send one command to the configured local Unix control socket",
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
        "-v",
        "-V",
        "--version",
        action="version",
        version=detailed_version(),
        help="Show version and exit",
    )
    args = parser.parse_args()
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
    if config.control.enabled and not writable_parent(config.control.socket_path):
        errors.append(
            "control socket directory cannot be created or written: "
            f"{Path(config.control.socket_path).parent}"
        )

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


def configuration_status(config: Config) -> list[str]:
    """Return a secret-free summary for the local status CLI mode."""
    security = "TLS" if config.network.tls else "plain TCP"
    channels = ", ".join(config.network.channels) or "none"
    modules = ", ".join(config.modules.enabled) or "none"
    feeds = "enabled" if config.feeds.enabled else "disabled"
    return [
        f"Network: {config.network.server}:{config.network.port} ({security})",
        f"Channels: {channels}",
        f"Built-in modules: {modules}",
        f"Feeds: {feeds} ({len(config.feeds.feeds)} configured)",
        f"Log root: {config.paths.log_root}",
        f"Data root: {config.paths.data_root}",
    ]


TerminalClient = LocalCommandClient
dispatch_terminal_command = dispatch_local_command


async def run_terminal_console(
    commands: CommandRegistry,
    config: Config,
    logger: logging.Logger,
    client: IRCClient,
) -> None:
    """Provide a local owner console without exposing a network listener."""
    if not sys.stdin.isatty():
        raise RuntimeError("--terminal-dcc requires an interactive terminal")
    terminal = TerminalClient(print)
    print("NovariusIRC local console. Type !help, !status, or exit.")
    while True:
        try:
            line = await asyncio.to_thread(input, "novariusirc> ")
        except EOFError:
            line = "exit"
        if not await dispatch_local_command(commands, config, logger, terminal, line):
            await client.stop()
            return


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
        await ctx.reply(ctx.tr("pong"))

    async def uptime(ctx: CommandContext, args: list[str]) -> None:
        seconds = int(time.monotonic() - start_time)
        await ctx.reply(ctx.tr("uptime: {seconds}s", seconds=seconds))

    async def version(ctx: CommandContext, args: list[str]) -> None:
        await ctx.reply(SIMPLE_VERSION)

    async def help_cmd(ctx: CommandContext, args: list[str]) -> None:
        if ctx.channel:
            lines = [
                ctx.tr(
                    "Commands (address {nick}):",
                    nick=getattr(ctx.client, "current_nick", config.network.nick),
                )
            ]
        else:
            lines = [ctx.tr("Commands ({prefix}):", prefix=config.bot.prefix)]
        for cmd in commands.list_commands(ctx.roles):
            lines.append(f"{cmd.name} - {ctx.tr(cmd.help_text)}")
        await ctx.reply(" | ".join(lines))

    commands.register("ping", ping, help_text="Health check", owner="core")
    commands.register("uptime", uptime, help_text="Show bot uptime", owner="core")
    commands.register("version", version, help_text="Show bot version", owner="core")
    commands.register("help", help_cmd, help_text="Show available commands", owner="core")


def register_runtime_commands(
    commands: CommandRegistry,
    client: IRCClient,
    modules: PluginManager,
    feeds: FeedEngine,
    start_time: float | None = None,
) -> None:
    """Register commands whose data exists only after core services are built."""
    runtime_started = time.monotonic() if start_time is None else start_time

    async def status(ctx: CommandContext, args: list[str]) -> None:
        connection = ctx.tr("connected" if client.is_connected else "disconnected")
        module_names = ", ".join(modules.active_builtin_modules) or "none"
        if module_names == "none":
            module_names = ctx.tr("none")
        feed_state = (
            ctx.tr("running")
            if feeds.is_running
            else (ctx.tr("idle") if feeds.config.enabled else ctx.tr("disabled"))
        )
        await ctx.reply(
            ctx.tr(
                "Status: {connection}; network={network}; modules={modules}; "
                "feeds={feeds}",
                connection=connection,
                network=client.network_name,
                modules=module_names,
                feeds=feed_state,
            )
        )

    async def botinfo(ctx: CommandContext, args: list[str]) -> None:
        connection = ctx.tr("connected" if client.is_connected else "disconnected")
        uptime_seconds = max(0, int(time.monotonic() - runtime_started))
        version_line, *diagnostics = detailed_version().splitlines()
        identity = ctx.tr(
            "Bot: {nick}; software={software}; network={network}; "
            "status={status}; uptime={uptime}s",
            nick=client.current_nick,
            software=version_line,
            network=client.network_name,
            status=connection,
            uptime=uptime_seconds,
        )
        diagnostic_keys = ("Runtime: {value}", "Features: {value}", "Optional: {value}")
        localized_diagnostics = [
            ctx.tr(key, value=line.partition(": ")[2])
            for key, line in zip(diagnostic_keys, diagnostics, strict=True)
        ]
        await ctx.reply(" | ".join((identity, *localized_diagnostics)))

    commands.register(
        "status", status, help_text="Show core service status", owner="core"
    )
    commands.register(
        "botinfo", botinfo, help_text="Show bot identity and features", owner="core"
    )


async def async_main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.check_config or args.status:
        errors = check_config(config)
        if errors:
            for error in errors:
                print(f"Configuration error: {error}", file=sys.stderr)
            raise SystemExit(1)
        if args.status:
            print("Configuration status:")
            for line in configuration_status(config):
                print(f"  {line}")
            return
        print("Configuration check passed.")
        return
    if args.ctl:
        if not config.control.enabled:
            raise RuntimeError("Local control socket is disabled in [control]")
        for line in await run_control_command(config.control.socket_path, args.ctl):
            print(line)
        return
    if args.terminal_dcc and not sys.stdin.isatty():
        raise RuntimeError("--terminal-dcc requires an interactive terminal")
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
    control = UnixControlServer(config.control.socket_path, commands, config, logger)

    client = IRCClient(config, commands, auth, plugins, moderation, logger)
    plugins.set_client(client)
    register_runtime_commands(commands, client, plugins, feeds, start_time)
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
        if config.control.enabled:
            await control.start()
        if args.terminal_dcc:
            terminal_task = asyncio.create_task(
                run_terminal_console(commands, config, logger, client),
                name="terminal-control-console",
            )
            try:
                await client.run()
            finally:
                terminal_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await terminal_task
        else:
            await client.run()
    finally:
        for handled_signal in handled_signals:
            with contextlib.suppress(NotImplementedError):
                loop.remove_signal_handler(handled_signal)
        await client.stop()
        await control.stop()
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
