import asyncio
import logging
import sys

import pytest

from novariusirc.core.commands import CommandContext, CommandRegistry
from novariusirc.core.config import Config
from novariusirc.core.plugins import PluginLoader


@pytest.mark.parametrize("behavior", ["reply", "hang", "oversize"])
def test_worker_commands_are_isolated_bounded_and_unloaded(tmp_path, behavior):
    package = tmp_path / "demo"
    package.mkdir()
    (package / "novarius_plugin.toml").write_text(
        '[plugin]\nname="demo"\nexecution="worker"\n'
        '[[commands]]\nname="demo"\nroles=["admin"]\n'
    )
    bodies = {
        "reply": 'return ["worker reply"]',
        "hang": 'while True: pass',
        "oversize": 'return ["x" * 401]',
    }
    (package / "__init__.py").write_text(
        'def handle(event, settings):\n    ' + bodies[behavior] + '\n'
    )
    config = Config.model_validate({
        "bot": {"language": "en"},
        "network": {"server": "test", "nick": "bot", "user": "bot", "realname": "bot"},
        "plugins": {"load": ["demo"], "worker_timeout_seconds": 2},
        "paths": {"data_root": str(tmp_path / "data")},
    })
    registry = CommandRegistry()
    loader = PluginLoader(tmp_path, ["demo"], registry, config, logging.getLogger("test"), None)
    replies = []

    class Client:
        async def send_privmsg(self, target, text):
            replies.append(text)

    async def scenario():
        await loader.load_all()
        assert "novarius_worker_plugin" not in sys.modules
        worker = loader.plugins["demo"]
        process = worker.process
        ctx = CommandContext("nick", "nick!user@host", "#test", "!demo", config,
                             Client(), logging.getLogger("test"), ["user"])
        await registry.dispatch(ctx)
        assert replies == ["You are not allowed to run this command."]
        ctx.roles = ["admin"]
        await registry.dispatch(ctx)
        if behavior == "reply":
            assert replies[-1] == "worker reply"
        else:
            assert replies[-1] == "Command failed."
            assert process.returncode is not None
        await loader.unload_all()
        assert process.returncode is not None
        assert registry.get("demo") is None

    asyncio.run(scenario())
