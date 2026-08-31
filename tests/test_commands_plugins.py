from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from novariusirc.core.auth import hostmask_match
from novariusirc.core.commands import CommandContext, CommandRegistry
from novariusirc.core.config import Config
from novariusirc.core.feeds import FeedEngine
from novariusirc.core.plugins import Plugin, PluginLoader, PluginManager
from novariusirc.core.protocol import irc_casefold


class ReplyClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send_privmsg(self, target: str, message: str) -> None:
        self.messages.append((target, message))


def minimal_config(**plugins: object) -> Config:
    return Config.model_validate(
        {
            "bot": {},
            "network": {
                "server": "irc.example.test",
                "nick": "bot",
                "user": "bot",
                "realname": "Bot",
            },
            "plugins": plugins,
        }
    )


def context(client: ReplyClient, message: str, roles: list[str]) -> CommandContext:
    return CommandContext(
        nick="alice",
        hostmask="alice!user@example.test",
        channel="#test",
        message=message,
        config=object(),
        client=client,
        logger=logging.getLogger("test.commands"),
        roles=roles,
    )


def test_aliases_roles_help_and_unregister_share_one_registry() -> None:
    registry = CommandRegistry(prefix="!", rate_limit_seconds=0)
    client = ReplyClient()

    async def handler(ctx: CommandContext, args: list[str]) -> None:
        await ctx.reply("ok " + " ".join(args))

    registry.register(
        "greet",
        handler,
        roles=("admin",),
        aliases=("hello",),
        owner="test",
    )

    assert asyncio.run(registry.dispatch(context(client, "!hello world", ["user"])))
    assert client.messages[-1][1] == "You are not allowed to run this command."

    assert asyncio.run(registry.dispatch(context(client, "!hello world", ["admin"])))
    assert client.messages[-1] == ("#test", "ok world")
    assert [command.name for command in registry.list_commands()] == ["greet"]
    assert registry.list_commands(["user"]) == []

    registry.unregister_owner("test")
    assert not asyncio.run(registry.dispatch(context(client, "!hello", ["owner"])))


def test_external_plugins_are_explicit_and_unload_cleanly(tmp_path: Path) -> None:
    plugin_file = tmp_path / "demo.py"
    plugin_file.write_text(
        """
from novariusirc.core.plugins import BasePlugin, command

class Demo(BasePlugin):
    name = "demo"

    @command(aliases=("hi",), role="admin")
    async def cmd_hello(self, ctx, args):
        await ctx.reply("plugin-ok")
""".strip(),
        encoding="utf-8",
    )
    config = minimal_config(enabled=True, directory=str(tmp_path), load=["demo"])
    registry = CommandRegistry()
    client = ReplyClient()
    loader = PluginLoader(
        tmp_path,
        config.plugins.load,
        registry,
        config,
        logging.getLogger("test.plugins"),
        client,
    )

    assert asyncio.run(loader.load_all()) == 1
    assert registry.get("hi") is not None
    asyncio.run(registry.dispatch(context(client, "!hi", ["admin"])))
    assert client.messages[-1][1] == "plugin-ok"

    asyncio.run(loader.unload_all())
    assert registry.get("hello") is None


def test_plugin_configuration_rejects_paths() -> None:
    try:
        minimal_config(load=["../outside"])
    except ValueError as exc:
        assert "invalid plugin names" in str(exc)
    else:
        raise AssertionError("unsafe plugin path was accepted")


def test_enabled_sasl_requires_complete_credentials() -> None:
    config = minimal_config()
    config.network.tls = True
    config.auth.sasl_enabled = True
    config.auth.sasl_username = "bot"
    try:
        config.validate_runtime_secrets()
    except ValueError as exc:
        assert "sasl_password" in str(exc)
    else:
        raise AssertionError("incomplete SASL configuration was accepted")


def test_sasl_and_certfp_require_tls() -> None:
    plain = minimal_config()
    plain.auth.sasl_enabled = True
    plain.auth.sasl_username = "bot"
    plain.auth.sasl_password = "secret"
    with pytest.raises(ValueError, match="SASL requires network.tls"):
        plain.validate_runtime_secrets()

    external = minimal_config()
    external.auth.certfp_enabled = True
    external.auth.certfp_cert_file = "client.pem"
    with pytest.raises(ValueError, match="CertFP requires network.tls"):
        external.validate_runtime_secrets()


def test_builtin_module_start_failure_rolls_back_started_modules() -> None:
    events: list[str] = []

    class TrackingModule(Plugin):
        def __init__(self, name: str, fail: bool = False) -> None:
            self.name = name
            self.fail = fail

        async def start(self) -> None:
            events.append(f"start:{self.name}")
            if self.fail:
                raise RuntimeError("start failed")

        async def stop(self) -> None:
            events.append(f"stop:{self.name}")

    config = minimal_config()
    logger = logging.getLogger("test.module-lifecycle")
    manager = PluginManager(
        config,
        CommandRegistry(),
        FeedEngine(config.feeds, logger, data_root=Path(config.paths.data_root)),
        object(),  # type: ignore[arg-type]
        logger,
    )
    manager.plugins = [TrackingModule("first"), TrackingModule("second", fail=True)]

    async def scenario() -> None:
        blocker = asyncio.Event()
        task = manager.tasks.create_task("first", blocker.wait(), name="test-blocker")
        with pytest.raises(RuntimeError, match="start failed"):
            await manager.start_builtin_modules()
        assert task.cancelled()

    asyncio.run(scenario())

    assert events == ["start:first", "start:second", "stop:second", "stop:first"]


def test_hostmask_matching_applies_irc_casemapping_only_to_nick() -> None:
    casefold = lambda value: irc_casefold(value, "rfc1459")
    assert hostmask_match("Nick^!*@*", "nick~!user@host", casefold)
    assert not hostmask_match("*!user^@host", "Nick!user~@host", casefold)
