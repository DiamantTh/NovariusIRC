from __future__ import annotations

import asyncio
import logging
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from novariusirc import __main__ as cli
from novariusirc import __version__
from novariusirc.__main__ import (
    TerminalClient,
    check_config,
    configuration_status,
    dispatch_terminal_command,
    register_builtin_commands,
    register_runtime_commands,
)
from novariusirc.core.auth import AuthManager
from novariusirc.core.commands import CommandRegistry
from novariusirc.core.config import Config, DatabaseConfig, WebAPIConfig
from novariusirc.core.database import SQLiteDatabase
from novariusirc.version import SIMPLE_VERSION, detailed_version


def test_package_version_matches_project_metadata() -> None:
    project_file = Path(__file__).parents[1] / "pyproject.toml"
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))
    assert __version__ == project["project"]["version"]


def test_web_api_defaults_to_local_reserved_port(monkeypatch: pytest.MonkeyPatch) -> None:
    config = WebAPIConfig()
    assert (config.enabled, config.host, config.port, config.allowed_networks) == (
        False,
        "127.0.0.1",
        9688,
        [],
    )

    monkeypatch.setenv("NOVARIUSIRC_WEB_API_ENABLED", "true")
    monkeypatch.setenv("NOVARIUSIRC_WEB_API_HOST", "0.0.0.0")
    monkeypatch.setenv("NOVARIUSIRC_WEB_API_PORT", "19688")
    config.resolve_env()

    assert (config.enabled, config.host, config.port) == (True, "0.0.0.0", 19688)


def test_web_api_network_allowlist_is_validated_and_canonicalized() -> None:
    config = WebAPIConfig(allowed_networks=["192.0.2.17", "192.0.2.0/24", "192.0.2.17"])
    assert config.allowed_networks == ["192.0.2.17/32", "192.0.2.0/24"]

    with pytest.raises(ValueError, match="IP addresses or CIDR networks"):
        WebAPIConfig(allowed_networks=["not-a-network"])


def test_typer_cli_groups_dispatch_to_existing_async_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked: list[object] = []

    async def fake_async_main(args) -> None:
        invoked.append(args)

    monkeypatch.setattr(cli, "async_main", fake_async_main)
    result = CliRunner().invoke(cli.app, ["--instance", "example", "config", "check"])

    assert result.exit_code == 0, result.output
    assert len(invoked) == 1
    assert invoked[0].check_config is True
    assert invoked[0].config == Path.home() / "NovariusIRC" / "instances/example/config"


def test_typer_cli_keeps_legacy_action_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked: list[object] = []

    async def fake_async_main(args) -> None:
        invoked.append(args)

    monkeypatch.setattr(cli, "async_main", fake_async_main)
    result = CliRunner().invoke(cli.app, ["--config", "chosen.toml", "--check-config"])

    assert result.exit_code == 0, result.output
    assert len(invoked) == 1
    assert invoked[0].check_config is True
    assert invoked[0].config == Path("chosen.toml")


@pytest.mark.parametrize(
    ("arguments", "attribute", "expected"),
    [
        ([], "check_config", False),
        (["run"], "check_config", False),
        (["console"], "terminal_dcc", True),
        (["ctl", "!status"], "ctl", "!status"),
        (["config", "status"], "status", True),
        (["database", "init"], "init_database", True),
        (["database", "upgrade"], "upgrade_database", True),
        (["database", "check"], "check_database", True),
        (["database", "backup"], "backup_database", True),
        (["database", "backups"], "list_backups", True),
        (["database", "restore", "archive.tar", "--replace", "--data"], "restore_data", True),
    ],
)
def test_typer_cli_commands_dispatch_expected_action(
    arguments: list[str],
    attribute: str,
    expected: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked: list[object] = []

    async def fake_async_main(args) -> None:
        invoked.append(args)

    monkeypatch.setattr(cli, "async_main", fake_async_main)
    result = CliRunner().invoke(cli.app, arguments)

    assert result.exit_code == 0, result.output
    assert len(invoked) == 1
    assert getattr(invoked[0], attribute) == expected


def test_cli_normalizes_shared_instance_options_after_subcommands() -> None:
    assert cli.normalize_cli_arguments(
        ["database", "check", "--instance", "example"]
    ) == ["--instance", "example", "database", "check"]


def test_main_normalizes_shared_instance_options_after_subcommands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_app(*, args: list[str], prog_name: str) -> None:
        captured["args"] = args
        captured["prog_name"] = prog_name

    monkeypatch.setattr(cli, "app", fake_app)
    monkeypatch.setattr(cli.sys, "argv", ["novariusirc", "database", "check", "--instance", "example"])
    cli.main()

    assert captured == {
        "args": ["--instance", "example", "database", "check"],
        "prog_name": "novariusirc",
    }


@pytest.mark.parametrize("flag", ["-v", "-V", "--version"])
def test_cli_version_aliases_are_identical(flag: str) -> None:
    result = CliRunner().invoke(cli.app, [flag])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == detailed_version()


def test_cli_accepts_positional_and_option_config_paths() -> None:
    assert cli.resolve_config_path(Path("instance/config.toml"), None, None, None) == Path(
        "instance/config.toml"
    )
    assert cli.resolve_config_path(Path("ignored.toml"), Path("selected.toml"), None, None) == Path(
        "selected.toml"
    )


def test_cli_instance_selectors_resolve_the_instance_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVARIUSIRC_INSTANCE_ROOT", "/opt/novariusirc/instances")
    assert cli.resolve_config_path(None, None, None, "example") == Path(
        "/opt/novariusirc/instances/example/config"
    )

    assert cli.resolve_config_path(None, None, Path("/data/example"), None) == Path(
        "/data/example/config"
    )


def test_cli_rejects_conflicting_or_unsafe_instance_selectors() -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        cli.resolve_config_path(None, Path("other"), None, "example")
    with pytest.raises(ValueError, match="simple instance name"):
        cli.resolve_config_path(None, None, None, "../example")


def test_terminal_console_dispatches_owner_commands() -> None:
    config = Config.model_validate(
        {
            "bot": {"language": "en"},
            "network": {
                "server": "irc.example.test",
                "nick": "bot",
                "user": "bot",
                "realname": "Bot",
            },
        }
    )
    commands = CommandRegistry(prefix="!", rate_limit_seconds=0)

    async def owner_command(ctx, args) -> None:
        await ctx.reply("terminal-ok")

    commands.register("owner-command", owner_command, roles=("owner",))
    terminal = TerminalClient()
    assert asyncio.run(
        dispatch_terminal_command(
            commands,
            config,
            logging.getLogger("test.terminal"),
            terminal,
            "owner-command",
        )
    )
    assert terminal.messages == ["terminal-ok"]
    assert not asyncio.run(
        dispatch_terminal_command(
            commands,
            config,
            logging.getLogger("test.terminal"),
            terminal,
            "exit",
        )
    )


def test_irc_version_is_simple_and_botinfo_is_detailed() -> None:
    config = Config.model_validate(
        {
            "bot": {"language": "en"},
            "network": {
                "server": "irc.example.test",
                "nick": "bot",
                "user": "bot",
                "realname": "Bot",
            },
        }
    )
    commands = CommandRegistry(prefix="!", rate_limit_seconds=0)
    register_builtin_commands(commands, config, start_time=0)
    terminal = TerminalClient()

    assert asyncio.run(
        dispatch_terminal_command(
            commands, config, logging.getLogger("test.version"), terminal, "version"
        )
    )
    assert terminal.messages[-1] == SIMPLE_VERSION

    register_runtime_commands(
        commands,
        SimpleNamespace(
            current_nick="RuntimeBot",
            is_connected=True,
            network_name="TestNet",
        ),  # type: ignore[arg-type]
        SimpleNamespace(active_builtin_modules=()),  # type: ignore[arg-type]
        SimpleNamespace(  # type: ignore[arg-type]
            config=SimpleNamespace(enabled=False), is_running=False
        ),
        start_time=0,
    )
    assert asyncio.run(
        dispatch_terminal_command(
            commands, config, logging.getLogger("test.botinfo"), terminal, "botinfo"
        )
    )
    botinfo = terminal.messages[-1]
    assert "Bot: RuntimeBot" in botinfo
    assert f"software={detailed_version().splitlines()[0]}" in botinfo
    assert "network=TestNet; status=connected" in botinfo
    assert "Runtime:" in botinfo


def test_owner_role_command_updates_the_database_cache(tmp_path: Path) -> None:
    config = Config.model_validate(
        {
            "bot": {"language": "en"},
            "network": {
                "server": "irc.example.test",
                "nick": "bot",
                "user": "bot",
                "realname": "Bot",
            },
        }
    )
    database = SQLiteDatabase(
        DatabaseConfig(path=str(tmp_path / "bot.sqlite3")), "TestBot"
    )
    database.initialize(create=True)
    database.bootstrap_owner_bindings([("hostmask", "owner!*@trusted.example")])
    auth = AuthManager(
        config.auth,
        config.roles,
        logging.getLogger("test.roles"),
        persistent_bindings=database.list_role_bindings(),
    )
    commands = CommandRegistry(prefix="!", rate_limit_seconds=0)
    register_builtin_commands(commands, config, start_time=0, auth=auth, database=database)
    terminal = TerminalClient()

    assert asyncio.run(
        dispatch_terminal_command(
            commands,
            config,
            logging.getLogger("test.roles"),
            terminal,
            "role add admin account staff-account",
        )
    )
    assert terminal.messages[-1] == "Added role binding #2."
    assert auth.roles_for_identity("staff", "staff!u@host", account="staff-account") == [
        "user",
        "admin",
    ]


def test_draft_capabilities_require_explicit_namespace() -> None:
    base = {
        "bot": {},
        "network": {
            "server": "irc.example.test",
            "nick": "bot",
            "user": "bot",
            "realname": "Bot",
            "ircv3_draft_capabilities": ["draft/chathistory"],
        },
    }
    assert Config.model_validate(base).network.ircv3_draft_capabilities == [
        "draft/chathistory"
    ]
    base["network"]["ircv3_draft_capabilities"] = ["chathistory"]
    with pytest.raises(ValueError, match="draft/ namespace"):
        Config.model_validate(base)


@pytest.mark.parametrize("extra", ["bad\ntext", "bad\x01text", "x" * 301])
def test_ctcp_version_extra_is_validated(extra: str) -> None:
    with pytest.raises(ValueError, match="extra text"):
        Config.model_validate(
            {
                "bot": {"ctcp_version_extra": extra},
                "network": {
                    "server": "irc.example.test",
                    "nick": "bot",
                    "user": "bot",
                    "realname": "Bot",
                },
            }
        )


def test_ctcp_version_extra_is_trimmed() -> None:
    config = Config.model_validate(
        {
            "bot": {"ctcp_version_extra": "  stable build  "},
            "network": {
                "server": "irc.example.test",
                "nick": "bot",
                "user": "bot",
                "realname": "Bot",
            },
        }
    )
    assert config.bot.ctcp_version_extra == "stable build"


@pytest.mark.parametrize(("field", "value"), [("nick", "bad nick"), ("user", ":bad")])
def test_registration_tokens_reject_invalid_framing(field: str, value: str) -> None:
    network = {
        "server": "irc.example.test",
        "nick": "bot",
        "user": "bot",
        "realname": "Bot",
    }
    network[field] = value
    with pytest.raises(ValueError, match="single parameters"):
        Config.model_validate({"bot": {}, "network": network})


def test_check_config_accepts_builtin_modules() -> None:
    config = Config.model_validate(
        {
            "bot": {},
            "network": {
                "server": "irc.example.test",
                "nick": "bot",
                "user": "bot",
                "realname": "Bot",
            },
            "modules": {"enabled": ["rss_announcer"]},
        }
    )
    assert check_config(config) == []
    assert configuration_status(config)[0] == "Network: irc.example.test:6667 (plain TCP)"


def test_check_config_reports_invalid_builtin_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NotAModule:
        pass

    module = type("Module", (), {"Plugin": NotAModule})
    monkeypatch.setattr("novariusirc.__main__.importlib.import_module", lambda _: module)
    config = Config.model_validate(
        {
            "bot": {},
            "network": {
                "server": "irc.example.test",
                "nick": "bot",
                "user": "bot",
                "realname": "Bot",
            },
            "modules": {"enabled": ["broken"]},
        }
    )
    assert check_config(config) == [
        "Built-in module 'broken' must export a Plugin subclass"
    ]


def test_check_config_reports_a_non_directory_runtime_parent(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    config = Config.model_validate(
        {
            "bot": {},
            "network": {
                "server": "irc.example.test",
                "nick": "bot",
                "user": "bot",
                "realname": "Bot",
            },
            "paths": {"log_root": str(blocked / "logs"), "data_root": str(tmp_path / "data")},
        }
    )
    assert any("log root cannot be created" in error for error in check_config(config))


def test_runtime_command_registration_includes_core_status() -> None:
    config = Config.model_validate(
        {
            "bot": {},
            "network": {
                "server": "irc.example.test",
                "nick": "bot",
                "user": "bot",
                "realname": "Bot",
            },
        }
    )
    commands = CommandRegistry()
    register_builtin_commands(commands, config, start_time=0)
    assert commands.get("status") is None
    assert commands.get("botinfo") is None
    register_runtime_commands(
        commands,
        SimpleNamespace(is_connected=False, network_name="TestNet"),  # type: ignore[arg-type]
        SimpleNamespace(active_builtin_modules=("rss_announcer",)),  # type: ignore[arg-type]
        SimpleNamespace(  # type: ignore[arg-type]
            config=SimpleNamespace(enabled=True), is_running=False
        ),
    )
    assert commands.get("status") is not None
    assert commands.get("botinfo") is not None
    assert [
        (command.name, command.roles, command.owner)
        for command in commands.list_commands()
    ] == [
        ("botinfo", ("user",), "core"),
        ("help", ("user",), "core"),
        ("ping", ("user",), "core"),
        ("status", ("user",), "core"),
        ("uptime", ("user",), "core"),
        ("version", ("user",), "core"),
    ]


def test_config_paths_are_relative_to_the_config_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[bot]
prefix = "!"

[network]
server = "irc.example.test"
nick = "bot"
user = "bot"
realname = "Bot"
""".strip(),
        encoding="utf-8",
    )

    config = Config.load(config_file)
    assert Path(config.plugins.directory) == tmp_path / "plugins"
    assert Path(config.paths.log_root) == tmp_path / "logs"
    assert Path(config.paths.data_root) == tmp_path / "data"
    assert Path(config.control.socket_path) == tmp_path / "run" / "novariusirc.sock"


def test_missing_config_path_is_not_silently_treated_as_env(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Configuration path not found"):
        Config.load(tmp_path / "missing.toml")


def test_all_example_toml_files_parse() -> None:
    root = Path(__file__).resolve().parents[1]
    examples = list((root / "config").glob("*.toml"))
    for example in examples:
        with example.open("rb") as handle:
            tomllib.load(handle)


def test_complete_example_configuration_validates(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    copies = {
        root / "config" / "config.example.toml": tmp_path / "config" / "config.toml",
        root / "config" / "secrets.example.toml": tmp_path / "config" / "secrets.toml",
        root / "config" / "feeds.example.toml": tmp_path / "config" / "feeds.toml",
    }
    for source, destination in copies.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())

    config = Config.load(tmp_path / "config")

    assert config.network.nick == "NovariusBot"
    assert len(config.feeds.feeds) == 3


def test_unknown_typed_config_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="extra_forbidden"):
        Config.model_validate(
            {
                "bot": {"prefix": "!", "typo": True},
                "network": {
                    "server": "irc.example.test",
                    "nick": "bot",
                    "user": "bot",
                    "realname": "Bot",
                },
            }
        )


@pytest.mark.parametrize("channel", ["", "#one,#two", "#bad channel", ":#bad"])
def test_config_rejects_ambiguous_channel_names(channel: str) -> None:
    with pytest.raises(ValueError, match="IRC channels"):
        Config.model_validate(
            {
                "bot": {},
                "network": {
                    "server": "irc.example.test",
                    "nick": "bot",
                    "user": "bot",
                    "realname": "Bot",
                    "channels": [channel],
                },
            }
        )


@pytest.mark.parametrize("channel", ["#novarius-irc", "#äöüß", "&Lokaler_Raum"])
def test_config_accepts_conservative_unicode_channel_names(channel: str) -> None:
    config = Config.model_validate(
        {
            "bot": {},
            "network": {
                "server": "irc.example.test",
                "nick": "bot",
                "user": "bot",
                "realname": "Bot",
                "channels": [channel],
            },
        }
    )
    assert config.network.channels == [channel]


def test_config_requires_opt_in_for_unusual_channel_names() -> None:
    base = {
        "bot": {},
        "network": {
            "server": "irc.example.test",
            "nick": "bot",
            "user": "bot",
            "realname": "Bot",
            "channels": ["#legacy/channel"],
        },
    }
    with pytest.raises(ValueError, match="allow_unusual_channel_names"):
        Config.model_validate(base)

    base["network"]["allow_unusual_channel_names"] = True
    assert Config.model_validate(base).network.channels == ["#legacy/channel"]


def test_environment_channel_override_uses_the_same_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[bot]

[network]
server = "irc.example.test"
nick = "bot"
user = "bot"
realname = "Bot"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVARIUSIRC_CHANNELS", "#legacy/channel")
    with pytest.raises(ValueError, match="allow_unusual_channel_names"):
        Config.load(config_file)


def test_explicit_missing_include_is_reported(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[bot]

[includes]
files = ["missing.toml"]

[network]
server = "irc.example.test"
nick = "bot"
user = "bot"
realname = "Bot"
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError, match="Included configuration file not found"):
        Config.load(config_file)


def test_sasl_cannot_be_configured_as_an_optional_ircv3_capability() -> None:
    with pytest.raises(ValueError, match=r"configured through \[auth\]"):
        Config.model_validate(
            {
                "bot": {},
                "network": {
                    "server": "irc.example.test",
                    "nick": "bot",
                    "user": "bot",
                    "realname": "Bot",
                    "ircv3_capabilities": ["sasl"],
                },
            }
        )


def test_environment_overrides_are_revalidated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[bot]

[network]
server = "irc.example.test"
nick = "bot"
user = "bot"
realname = "Bot"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVARIUSIRC_CHANNELS", "#good,#bad channel")

    with pytest.raises(ValueError, match="IRC channels"):
        Config.load(config_file)
