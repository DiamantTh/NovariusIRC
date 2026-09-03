"""CLI entry point for NovariusIRC."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
import os
import shutil
import signal
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated

import typer

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
from novariusirc.core.web_api import WebAPIServer
from novariusirc.core.workers import WorkerPool
from novariusirc.version import SIMPLE_VERSION, detailed_version


def resolve_config_path(
    config_path: Path | None,
    config_option: Path | None,
    instancedir: Path | None,
    instance: str | None,
) -> Path:
    """Resolve the one supported configuration selector for a CLI invocation."""
    if config_option is not None:
        if instancedir is not None or instance is not None:
            raise ValueError("--config cannot be combined with --instancedir or --instance")
        return config_option
    if config_path is not None and (instancedir is not None or instance is not None):
        raise ValueError("config path cannot be combined with --instancedir or --instance")
    if instance is not None:
        instance = instance.strip()
        if not instance or instance in {".", ".."} or "/" in instance or "\\" in instance:
            raise ValueError("--instance must be a simple instance name")
        instance_root = Path(
            os.getenv(
                "NOVARIUSIRC_INSTANCE_ROOT",
                str(Path.home() / "NovariusIRC" / "instances"),
            )
        )
        return instance_root / instance / "config"
    if instancedir is not None:
        return instancedir / "config"
    return config_path or Path("./config")


@dataclass(frozen=True)
class CLIArguments:
    """Normalized command-line state shared by Typer commands and the runtime."""

    config: Path
    status: bool = False
    terminal_dcc: bool = False
    ctl: str | None = None
    foreground: bool = False
    check_config: bool = False
    init_database: bool = False
    upgrade_database: bool = False
    check_database: bool = False
    backup_database: bool = False
    list_backups: bool = False
    restore_database: Path | None = None
    replace_database: bool = False
    restore_data: bool = False


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
    backups: BackupManager | None = None,
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
        for cmd in commands.list_commands(ctx.roles, include_local=ctx.is_local):
            lines.append(f"{cmd.name} - {ctx.tr(cmd.help_text)}")
        await ctx.reply(" | ".join(lines))

    commands.register("ping", ping, help_text="Health check", owner="core")
    commands.register("uptime", uptime, help_text="Show bot uptime", owner="core")
    commands.register("version", version, help_text="Show bot version", owner="core")
    commands.register("help", help_cmd, help_text="Show available commands", owner="core")

    if database:

        async def db(ctx: CommandContext, args: list[str]) -> None:
            usage = ctx.invocation("db status | check | backup | backups")
            if len(args) != 1:
                await ctx.reply(ctx.tr("Usage: {command}", command=usage))
                return
            action = args[0].lower()
            if action in {"status", "check"}:
                try:
                    status = await asyncio.to_thread(database.check)
                except DatabaseError as exc:
                    await ctx.reply(ctx.tr("Database check failed: {error}", error=exc))
                    return
                await ctx.reply(
                    ctx.tr(
                        "Database: backend={backend}; schema={schema}; integrity={integrity}; location={location}",
                        backend=status.backend,
                        schema=status.schema_version,
                        integrity=status.integrity,
                        location=status.location,
                    )
                )
                return
            if backups is None or not backups.config.enabled:
                await ctx.reply(ctx.tr("Backups are disabled in [backups]."))
                return
            if action == "backup":
                try:
                    result = await asyncio.to_thread(backups.create)
                except BackupError as exc:
                    await ctx.reply(ctx.tr("Database backup failed: {error}", error=exc))
                    return
                await ctx.reply(
                    ctx.tr(
                        "Backup created: {path}; compression={compression}",
                        path=result.path,
                        compression="bzip3" if result.compressed else "none",
                    )
                )
                return
            if action in {"backups", "list"}:
                archived = await asyncio.to_thread(backups.list)
                if not archived:
                    await ctx.reply(ctx.tr("No backups are available."))
                    return
                for path in archived:
                    await ctx.reply(ctx.tr("Backup: {path}", path=path))
                return
            await ctx.reply(ctx.tr("Usage: {command}", command=usage))

        commands.register(
            "db",
            db,
            roles=("owner",),
            help_text="Inspect local database and backups",
            owner="core",
            local_only=True,
        )

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


async def async_main(args: CLIArguments) -> None:
    config = load_config(args.config)
    if (
        args.init_database
        or args.upgrade_database
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
        if args.upgrade_database:
            result = database.upgrade_safely()
            status = result.status
            if result.previous_copy:
                print(
                    "Database upgraded safely: "
                    f"previous={result.previous_copy}; "
                    f"sha256={result.previous_sha256}; "
                    f"upgraded_sha256={result.upgraded_sha256}"
                )
        else:
            status = database.initialize(create=True) if args.init_database else database.check()
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
    backups: BackupManager | None = None
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
        backups = BackupManager(
            config.backups,
            database,
            config.bot.name or config.network.nick,
            Path(config.paths.data_root),
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
    register_builtin_commands(
        commands, config, start_time, auth=auth, database=database, backups=backups
    )

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
    web_api = WebAPIServer(
        config.web_api, client, feeds, database, start_time, logger
    )
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
        await web_api.start()
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
        await web_api.stop()
        await client.stop()
        await control.stop()
        await feeds.stop()
        await plugins.stop()
        await tasks.shutdown(timeout=config.lifecycle.module_stop_timeout_seconds)
        await workers.shutdown()


app = typer.Typer(
    name="novariusirc",
    help="Run and operate a NovariusIRC instance.",
    invoke_without_command=True,
    no_args_is_help=False,
)
config_app = typer.Typer(help="Validate and inspect an instance configuration.")
database_app = typer.Typer(help="Maintain the persistent database and backups.")
app.add_typer(config_app, name="config")
app.add_typer(database_app, name="database")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(detailed_version())
        raise typer.Exit()


def _build_cli_args(
    config_path: Path | None,
    config_option: Path | None,
    instancedir: Path | None,
    instance: str | None,
    *,
    status: bool = False,
    terminal_dcc: bool = False,
    ctl: str | None = None,
    foreground: bool = False,
    check_config: bool = False,
    init_database: bool = False,
    upgrade_database: bool = False,
    check_database: bool = False,
    backup_database: bool = False,
    list_backups: bool = False,
    restore_database: Path | None = None,
    replace_database: bool = False,
    restore_data: bool = False,
) -> CLIArguments:
    return CLIArguments(
        config=resolve_config_path(config_path, config_option, instancedir, instance),
        status=status,
        terminal_dcc=terminal_dcc,
        ctl=ctl,
        foreground=foreground,
        check_config=check_config,
        init_database=init_database,
        upgrade_database=upgrade_database,
        check_database=check_database,
        backup_database=backup_database,
        list_backups=list_backups,
        restore_database=restore_database,
        replace_database=replace_database,
        restore_data=restore_data,
    )


def _with_cli_args(args: CLIArguments, **updates: object) -> CLIArguments:
    return replace(args, **updates)


def _context_args(ctx: typer.Context) -> CLIArguments:
    if not isinstance(ctx.obj, CLIArguments):
        raise TypeError("CLI context was not initialized")
    return ctx.obj


def _run_cli_action(args: CLIArguments, **updates: object) -> None:
    asyncio.run(async_main(_with_cli_args(args, **updates)))


@app.callback()
def root_command(
    ctx: typer.Context,
    config_option: Annotated[
        Path | None,
        typer.Option("-c", "--config", help="Path to config.toml or 'env'."),
    ] = None,
    instancedir: Annotated[
        Path | None,
        typer.Option("--instancedir", help="Instance directory containing config/config.toml."),
    ] = None,
    instance: Annotated[
        str | None,
        typer.Option("--instance", help="Instance below $NOVARIUSIRC_INSTANCE_ROOT."),
    ] = None,
    foreground: Annotated[
        bool,
        typer.Option("-f", "--foreground", help="Log foreground startup mode."),
    ] = False,
    terminal_dcc: Annotated[
        bool,
        typer.Option("-t", "--terminal-dcc", hidden=True),
    ] = False,
    ctl: Annotated[str | None, typer.Option("--ctl", hidden=True)] = None,
    status: Annotated[
        bool,
        typer.Option("-s", "--status", "--channel-stats", hidden=True),
    ] = False,
    check_config: Annotated[bool, typer.Option("--check-config", hidden=True)] = False,
    init_database: Annotated[bool, typer.Option("--init-database", hidden=True)] = False,
    upgrade_database: Annotated[bool, typer.Option("--upgrade-database", hidden=True)] = False,
    check_database: Annotated[bool, typer.Option("--check-database", hidden=True)] = False,
    backup_database: Annotated[bool, typer.Option("--backup-database", hidden=True)] = False,
    list_backups: Annotated[bool, typer.Option("--list-backups", hidden=True)] = False,
    restore_database: Annotated[Path | None, typer.Option("--restore-database", hidden=True)] = None,
    replace_database: Annotated[bool, typer.Option("--replace-database", hidden=True)] = False,
    restore_data: Annotated[bool, typer.Option("--restore-data", hidden=True)] = False,
    version: Annotated[
        bool,
        typer.Option("-v", "-V", "--version", callback=_version_callback, is_eager=True),
    ] = False,
) -> None:
    """Set the instance selector shared by all commands."""
    del version
    try:
        args = _build_cli_args(
            None,
            config_option,
            instancedir,
            instance,
            status=status,
            terminal_dcc=terminal_dcc,
            ctl=ctl,
            foreground=foreground,
            check_config=check_config,
            init_database=init_database,
            upgrade_database=upgrade_database,
            check_database=check_database,
            backup_database=backup_database,
            list_backups=list_backups,
            restore_database=restore_database,
            replace_database=replace_database,
            restore_data=restore_data,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    ctx.obj = args
    legacy_actions = (
        status,
        terminal_dcc,
        ctl is not None,
        check_config,
        init_database,
        upgrade_database,
        check_database,
        backup_database,
        list_backups,
        restore_database is not None,
    )
    if ctx.invoked_subcommand is not None:
        if any(legacy_actions):
            raise typer.BadParameter("legacy action flags cannot be combined with a subcommand")
        return
    _run_cli_action(args)


@app.command("run")
def run_command(ctx: typer.Context) -> None:
    """Run the IRC bot (the default when no subcommand is supplied)."""
    _run_cli_action(_context_args(ctx))


@app.command("console")
def console_command(ctx: typer.Context) -> None:
    """Run the bot with an interactive local terminal console."""
    _run_cli_action(_context_args(ctx), terminal_dcc=True)


@app.command("ctl")
def control_command(
    ctx: typer.Context,
    command: Annotated[str, typer.Argument(help="Registered local control command.")],
) -> None:
    """Send one command to the running bot's Unix control socket."""
    _run_cli_action(_context_args(ctx), ctl=command)


@config_app.command("check")
def config_check_command(ctx: typer.Context) -> None:
    """Validate configuration and built-in modules without IRC connectivity."""
    _run_cli_action(_context_args(ctx), check_config=True)


@config_app.command("status")
def config_status_command(ctx: typer.Context) -> None:
    """Print the secret-free configured core status without IRC connectivity."""
    _run_cli_action(_context_args(ctx), status=True)


@database_app.command("init")
def database_init_command(ctx: typer.Context) -> None:
    """Initialize a database or safely upgrade an existing one."""
    _run_cli_action(_context_args(ctx), init_database=True)


@database_app.command("upgrade")
def database_upgrade_command(ctx: typer.Context) -> None:
    """Safely upgrade an existing database using a verified copy."""
    _run_cli_action(_context_args(ctx), upgrade_database=True)


@database_app.command("check")
def database_check_command(ctx: typer.Context) -> None:
    """Check configured database integrity and schema."""
    _run_cli_action(_context_args(ctx), check_database=True)


@database_app.command("backup")
def database_backup_command(ctx: typer.Context) -> None:
    """Create one verified offline database and data backup."""
    _run_cli_action(_context_args(ctx), backup_database=True)


@database_app.command("backups")
def database_backups_command(ctx: typer.Context) -> None:
    """List available backups for the selected instance."""
    _run_cli_action(_context_args(ctx), list_backups=True)


@database_app.command("restore")
def database_restore_command(
    ctx: typer.Context,
    archive: Annotated[Path, typer.Argument(help="Backup archive to restore.")],
    replace: Annotated[
        bool,
        typer.Option("--replace", help="Allow replacing the configured database."),
    ] = False,
    data: Annotated[
        bool,
        typer.Option("--data", help="Also restore archived data files."),
    ] = False,
) -> None:
    """Restore one offline backup archive."""
    _run_cli_action(
        _context_args(ctx),
        restore_database=archive,
        replace_database=replace,
        restore_data=data,
    )


def normalize_cli_arguments(arguments: list[str]) -> list[str]:
    """Allow shared instance selectors before or after a Typer subcommand."""
    value_options = {"-c", "--config", "--instancedir", "--instance"}
    flag_options = {"-f", "--foreground"}
    global_options: list[str] = []
    remaining: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in value_options:
            if index + 1 >= len(arguments):
                remaining.append(argument)
            else:
                global_options.extend((argument, arguments[index + 1]))
                index += 1
        elif (
            any(argument.startswith(f"{option}=") for option in value_options if option != "-c")
            or argument in flag_options
        ):
            global_options.append(argument)
        else:
            remaining.append(argument)
        index += 1
    return [*global_options, *remaining]


def main() -> None:
    configure_event_loop()
    try:
        command_names = {"run", "console", "ctl", "config", "database"}
        arguments = sys.argv[1:]
        # The earlier CLI accepted a config path as its first positional
        # argument. Typer command groups need that position for their names,
        # so preserve the old invocation by converting only unknown first
        # words to the explicit --config form before Typer parses them.
        if arguments and not arguments[0].startswith("-") and arguments[0] not in command_names:
            arguments = ["--config", arguments[0], *arguments[1:]]
        arguments = normalize_cli_arguments(arguments)
        app(args=arguments, prog_name="novariusirc")
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI entry points must fail concisely
        print(f"NovariusIRC could not start: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
