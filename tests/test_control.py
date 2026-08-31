from __future__ import annotations

import asyncio
import logging
import stat

from novariusirc.core.commands import CommandRegistry
from novariusirc.core.config import Config
from novariusirc.core.control import UnixControlServer, run_control_command


def test_unix_control_socket_dispatches_owner_commands(tmp_path) -> None:
    async def scenario() -> None:
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
            await ctx.reply("socket-ok")

        commands.register("owner-command", owner_command, roles=("owner",))
        socket_path = tmp_path / "control.sock"
        server = UnixControlServer(
            socket_path, commands, config, logging.getLogger("test.control")
        )
        await server.start()
        try:
            assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
            assert await run_control_command(socket_path, "owner-command") == ["socket-ok"]
        finally:
            await server.stop()
        assert not socket_path.exists()

    asyncio.run(scenario())


def test_unix_control_socket_refuses_an_active_socket(tmp_path) -> None:
    async def scenario() -> None:
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
        socket_path = tmp_path / "control.sock"
        first = UnixControlServer(
            socket_path, commands, config, logging.getLogger("test.control")
        )
        second = UnixControlServer(
            socket_path, commands, config, logging.getLogger("test.control")
        )
        await first.start()
        try:
            try:
                await second.start()
            except RuntimeError as exc:
                assert "already in use" in str(exc)
            else:
                raise AssertionError("second control server unexpectedly started")
        finally:
            await first.stop()

    asyncio.run(scenario())
