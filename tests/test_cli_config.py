from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from novariusirc.__main__ import parse_args
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


def test_unimplemented_cli_modes_fail_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["novariusirc", "--channel-stats"])
    with pytest.raises(SystemExit) as exc:
        parse_args()
    assert exc.value.code == 2


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
