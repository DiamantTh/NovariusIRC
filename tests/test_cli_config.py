from __future__ import annotations

import asyncio
import logging
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from novariusirc.__main__ import (
    TerminalClient,
    check_config,
    configuration_status,
    dispatch_terminal_command,
    parse_args,
    register_builtin_commands,
    register_runtime_commands,
)
from novariusirc.core.commands import CommandRegistry
from novariusirc.core.config import Config


def test_cli_accepts_positional_and_option_config_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["novariusirc", "instance/config.toml"])
    assert parse_args().config == Path("instance/config.toml")

    monkeypatch.setattr(
        sys,
        "argv",
        ["novariusirc", "ignored.toml", "--config", "selected.toml"],
    )
    assert parse_args().config == Path("selected.toml")


def test_terminal_dcc_mode_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["novariusirc", "--terminal-dcc"])
    assert parse_args().terminal_dcc


def test_ctl_command_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["novariusirc", "--ctl", "status"])
    assert parse_args().ctl == "status"


def test_terminal_console_dispatches_owner_commands() -> None:
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


def test_status_cli_flag_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["novariusirc", "--status"])
    assert parse_args().status


def test_check_config_cli_flag_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["novariusirc", "--check-config"])
    assert parse_args().check_config


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


def test_ctcp_version_template_is_validated() -> None:
    with pytest.raises(ValueError, match="version.*placeholder"):
        Config.model_validate(
            {
                "bot": {"ctcp_version_reply": "Bot {platform}"},
                "network": {
                    "server": "irc.example.test",
                    "nick": "bot",
                    "user": "bot",
                    "realname": "Bot",
                },
            }
        )


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
    register_runtime_commands(
        commands,
        SimpleNamespace(is_connected=False, network_name="TestNet"),  # type: ignore[arg-type]
        SimpleNamespace(active_builtin_modules=("rss_announcer",)),  # type: ignore[arg-type]
        SimpleNamespace(  # type: ignore[arg-type]
            config=SimpleNamespace(enabled=True), is_running=False
        ),
    )
    assert commands.get("status") is not None


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
    examples = [root / "config.example.toml", root / "secrets.example.toml"]
    examples.extend((root / "config").glob("*.toml"))
    for example in examples:
        with example.open("rb") as handle:
            tomllib.load(handle)


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
