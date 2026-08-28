from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from novariusirc.core.commands import CommandContext, CommandRegistry
from novariusirc.core.config import Config
from novariusirc.core.plugins import PluginLoader


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
    config.auth.sasl_enabled = True
    config.auth.sasl_username = "bot"
    try:
        config.validate_runtime_secrets()
    except ValueError as exc:
        assert "sasl_password" in str(exc)
    else:
        raise AssertionError("incomplete SASL configuration was accepted")
