"""CLI entry point for NovariusIRC."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import logging
import os
import shutil
import signal
import sys
import time
from pathlib import Path

from novariusirc.core.auth import AuthManager
from novariusirc.core.backups import BackupError, BackupManager
from novariusirc.core.client import IRCClient
from novariusirc.core.commands import CommandContext, CommandRegistry
from novariusirc.core.config import Config, load_config
from novariusirc.core.control import (
    LocalCommandClient,
    UnixControlServer,
    dispatch_local_command,
    run_control_command,
)
from novariusirc.core.database import DatabaseBackend, DatabaseError, create_database
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
        "--init-database",
        action="store_true",
        help="Initialize the configured database and exit",
    )
    parser.add_argument(
        "--check-database",
        action="store_true",
        help="Check the configured database integrity and schema, then exit",
    )
    parser.add_argument(
        "--backup-database",
        action="store_true",
        help="Create one verified offline database and data backup, then exit",
    )
    parser.add_argument(
        "--list-backups",
        action="store_true",
        help="List backups for the configured bot instance, then exit",
    )
    parser.add_argument(
        "--restore-database",
        type=Path,
        help="Restore one offline backup archive",
    )
    parser.add_argument(
        "--replace-database",
        action="store_true",
        help="Allow --restore-database to replace the configured database",
    )
    parser.add_argument(
        "--restore-data",
        action="store_true",
        help="Also copy archived data files during --restore-database",
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
        *(
            [("backup directory", config.backups.directory)]
            if config.backups.enabled
            else []
        ),
    ):
        if not writable_parent(path):
            errors.append(f"{label} cannot be created or written: {path}")
    if config.control.enabled and not writable_parent(config.control.socket_path):
        errors.append(
            "control socket directory cannot be created or written: "
            f"{Path(config.control.socket_path).parent}"
        )

    if config.database.enabled:
        try:
            database = create_database(config.database, config.bot.name or config.network.nick)
            if config.database.backend == "sqlite":
                assert config.database.path is not None
                if Path(config.database.path).exists():
                    database.check()
                    if not any(
                        binding.role_name == "owner"
                        for binding in database.list_role_bindings()
                    ) and not owner_seed_bindings(config):
                        errors.append(
                            "database has no owner binding; configure [owner_bootstrap] "
                            "or NOVARIUSIRC_OWNER_HOSTMASK before startup"
                        )
                elif not writable_parent(config.database.path):
                    errors.append(
                        f"database directory cannot be created or written: "
                        f"{Path(config.database.path).parent}"
                    )
                else:
                    errors.append(
                        "database is not initialized; run --init-database: "
                        f"{config.database.path}"
                    )
        except DatabaseError as exc:
            errors.append(str(exc))
    if config.backups.enabled and config.backups.compression == "bzip3" and not shutil.which(
        "bzip3"
    ):
        errors.append("bzip3 is required for backups.compression = 'bzip3'")

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


def owner_seed_bindings(config: Config) -> list[tuple[str, str]]:
    """Return one-time owner seeds, including the legacy config hostmasks."""
    configured = [("hostmask", entry.hostmask) for entry in config.roles.owners]
    return list(dict.fromkeys([*configured, *config.owner_bootstrap.bindings()]))


def configuration_status(config: Config) -> list[str]:
    """Return a secret-free summary for the local status CLI mode."""
    security = "TLS" if config.network.tls else "plain TCP"
    channels = ", ".join(config.network.channels) or "none"
    modules = ", ".join(config.modules.enabled) or "none"
    feeds = "enabled" if config.feeds.enabled else "disabled"
    database = (
        f"{config.database.backend} ({config.database.path})"
        if config.database.enabled and config.database.backend == "sqlite"
        else (config.database.backend if config.database.enabled else "disabled")
    )
    return [
        f"Network: {config.network.server}:{config.network.port} ({security})",
        f"Channels: {channels}",
        f"Built-in modules: {modules}",
        f"Feeds: {feeds} ({len(config.feeds.feeds)} configured)",
        f"Database: {database}",
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
    commands: CommandRegistry,
    config: Config,
    start_time: float,
    *,
    auth: AuthManager | None = None,
    database: DatabaseBackend | None = None,
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

    if database and auth:

        async def role(ctx: CommandContext, args: list[str]) -> None:
            usage = ctx.invocation("role list | add <role> <hostmask|account|certfp> <value> | remove <id>")
            if not args:
                await ctx.reply(ctx.tr("Usage: {command}", command=usage))
                return
            action = args[0].lower()
            if action in {"list", "ls"} and len(args) == 1:
                bindings = database.list_role_bindings()
                if not bindings:
                    await ctx.reply(ctx.tr("No role bindings are configured."))
                    return
                for binding in bindings:
                    await ctx.reply(
                        ctx.tr(
                            "Role binding #{id}: {role} {type} {value}",
                            id=binding.id,
                            role=binding.role_name,
                            type=binding.binding_type,
                            value=binding.binding_value,
                        )
                    )
                return
            if action == "add" and len(args) >= 4:
                try:
                    binding = database.add_role_binding(
                        args[1], args[2], " ".join(args[3:])
                    )
                except DatabaseError as exc:
                    await ctx.reply(str(exc))
                    return
                auth.set_persistent_bindings(database.list_role_bindings())
                await ctx.reply(
                    ctx.tr("Added role binding #{id}.", id=binding.id)
                )
                return
            if action in {"remove", "delete", "del"} and len(args) == 2:
                try:
                    binding_id = int(args[1])
                except ValueError:
                    await ctx.reply(ctx.tr("Usage: {command}", command=usage))
                    return
                bindings = database.list_role_bindings()
                binding = next((item for item in bindings if item.id == binding_id), None)
                if binding is None:
                    await ctx.reply(ctx.tr("Role binding #{id} was not found.", id=binding_id))
                    return
                if binding.role_name == "owner" and sum(
                    item.role_name == "owner" for item in bindings
                ) == 1:
                    await ctx.reply(ctx.tr("Cannot remove the last owner binding."))
                    return
                database.remove_role_binding(binding_id)
                auth.set_persistent_bindings(database.list_role_bindings())
                await ctx.reply(ctx.tr("Removed role binding #{id}.", id=binding_id))
                return
            await ctx.reply(ctx.tr("Usage: {command}", command=usage))

        commands.register(
            "role",
            role,
            roles=("owner",),
            help_text="Manage persistent role bindings",
            owner="core",
        )


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
    if (
        args.init_database
        or args.check_database
        or args.backup_database
        or args.list_backups
        or args.restore_database
    ):
        if not config.database.enabled:
            raise RuntimeError("Database is disabled in [database]")
        database = create_database(config.database, config.bot.name or config.network.nick)
        backups = BackupManager(
            config.backups,
            database,
            config.bot.name or config.network.nick,
            Path(config.paths.data_root),
        )
        if args.list_backups:
            for backup in backups.list():
                print(backup)
            return
        if args.backup_database:
            try:
                result = backups.create()
            except BackupError as exc:
                raise RuntimeError(f"Backup failed: {exc}") from exc
            print(
                f"Backup created: {result.path}; "
                f"compression={'bzip3' if result.compressed else 'none'}"
            )
            return
        if args.restore_database:
            try:
                backups.restore(
                    args.restore_database,
                    replace=args.replace_database,
                    restore_data=args.restore_data,
                )
            except BackupError as exc:
                raise RuntimeError(f"Restore failed: {exc}") from exc
            print(f"Database restored from: {args.restore_database}")
            return
        status = (
            database.initialize(create=True)
            if args.init_database
            else database.check()
        )
        if args.init_database:
            seeded = database.bootstrap_owner_bindings(owner_seed_bindings(config))
            if seeded:
                print(f"Seeded {len(seeded)} owner binding(s).")
        print(
            f"Database {status.integrity}: backend={status.backend}; "
            f"schema={status.schema_version}; location={status.location}"
        )
        return
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

    database: DatabaseBackend | None = None
    if config.database.enabled:
        database = create_database(config.database, config.bot.name or config.network.nick)
        status = database.check()
        seeded = database.bootstrap_owner_bindings(owner_seed_bindings(config))
        if seeded:
            logger.info("Seeded %s owner binding(s) from bootstrap configuration", len(seeded))
        logger.info(
            "Database ready: backend=%s schema=%s location=%s",
            status.backend,
            status.schema_version,
            status.location,
        )

    if args.foreground:
        logger.info("Starting in foreground mode")

    auth = AuthManager(
        config.auth,
        config.roles,
        logger,
        persistent_bindings=database.list_role_bindings() if database else None,
    )
    commands = CommandRegistry(
        prefix=config.bot.prefix, rate_limit_seconds=config.commands.rate_limit_seconds
    )
    start_time = time.monotonic()
    register_builtin_commands(commands, config, start_time, auth=auth, database=database)

    feeds = FeedEngine(
        config.feeds,
        logger,
        data_root=Path(config.paths.data_root),
        state_store=database,
    )
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
