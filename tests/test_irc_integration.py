from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from novariusirc.core.auth import AuthManager
from novariusirc.core.client import IRCClient
from novariusirc.core.commands import CommandRegistry
from novariusirc.core.config import Config
from novariusirc.core.moderation import ModerationManager


class RecordingPlugins:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.events: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def on_message(
        self,
        nick: str,
        channel: str,
        message: str,
        **metadata: Any,
    ) -> None:
        self.messages.append(
            {"nick": nick, "channel": channel, "message": message, **metadata}
        )

    async def _event(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.events.append((name, args, kwargs))

    async def on_join(self, *args: Any, **kwargs: Any) -> None:
        await self._event("JOIN", *args, **kwargs)

    async def on_action(self, *args: Any, **kwargs: Any) -> None:
        await self._event("ACTION", *args, **kwargs)

    async def on_notice(self, *args: Any, **kwargs: Any) -> None:
        await self._event("NOTICE", *args, **kwargs)

    async def on_account(self, *args: Any, **kwargs: Any) -> None:
        await self._event("ACCOUNT", *args, **kwargs)

    async def on_part(self, *args: Any, **kwargs: Any) -> None:
        await self._event("PART", *args, **kwargs)

    async def on_quit(self, *args: Any, **kwargs: Any) -> None:
        await self._event("QUIT", *args, **kwargs)

    async def on_nick_change(self, *args: Any, **kwargs: Any) -> None:
        await self._event("NICK", *args, **kwargs)

    async def on_kick(self, *args: Any, **kwargs: Any) -> None:
        await self._event("KICK", *args, **kwargs)

    async def on_mode(self, *args: Any, **kwargs: Any) -> None:
        await self._event("MODE", *args, **kwargs)

    async def on_topic(self, *args: Any, **kwargs: Any) -> None:
        await self._event("TOPIC", *args, **kwargs)

    async def on_away(self, *args: Any, **kwargs: Any) -> None:
        await self._event("AWAY", *args, **kwargs)

    async def on_chghost(self, *args: Any, **kwargs: Any) -> None:
        await self._event("CHGHOST", *args, **kwargs)

    async def on_invite(self, *args: Any, **kwargs: Any) -> None:
        await self._event("INVITE", *args, **kwargs)

    async def on_tagmsg(self, *args: Any, **kwargs: Any) -> None:
        await self._event("TAGMSG", *args, **kwargs)


def test_client_negotiates_ircv3_and_handles_server_features() -> None:
    async def scenario() -> None:
        server_received: list[str] = []
        server_finished = asyncio.Event()

        async def read_line(reader: asyncio.StreamReader) -> str:
            line = await asyncio.wait_for(reader.readline(), timeout=2)
            decoded = line.decode().rstrip("\r\n")
            server_received.append(decoded)
            return decoded

        async def handle_client(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                assert await read_line(reader) == "CAP LS 302"
                assert await read_line(reader) == "NICK Bot"
                assert await read_line(reader) == "USER bot 0 * :Test Bot"
                writer.write(
                    b":irc.test CAP * LS :account-notify account-tag away-notify chghost extended-join invite-notify message-tags multi-prefix server-time userhost-in-names\r\n"
                )
                await writer.drain()
                request = await read_line(reader)
                assert request.startswith("CAP REQ :")
                requested = set(request.partition(":")[2].split())
                assert requested == {
                    "account-notify",
                    "account-tag",
                    "away-notify",
                    "chghost",
                    "extended-join",
                    "invite-notify",
                    "message-tags",
                    "multi-prefix",
                    "server-time",
                    "userhost-in-names",
                }
                writer.write(f":irc.test CAP * ACK :{' '.join(requested)}\r\n".encode())
                await writer.drain()
                assert await read_line(reader) == "CAP END"

                writer.write(b":irc.test 001 Bot :Welcome\r\n")
                writer.write(
                    b":irc.test 005 Bot CASEMAPPING=rfc1459-strict CHANTYPES=# PREFIX=(qaohv)~&@%+ CHANMODES=beI,k,l,imnpst STATUSMSG=@+ NETWORK=TestNet :supported\r\n"
                )
                writer.write(
                    b"@time=2026-08-29T01:02:03.456Z PING :container-check\r\n"
                )
                await writer.drain()
                assert await read_line(reader) == "PONG :container-check"

                writer.write(
                    b"@time=2026-08-29T01:02:04.000Z :Nick[!user@old.host JOIN #room Alice :Alice Example\r\n"
                    b":irc.test 353 Bot = #room :@+Nick{!user@old.host Other!other@other.host\r\n"
                    b":irc.test 366 Bot #room :End of NAMES\r\n"
                    b":irc.test 324 Bot #room +ntk secret\r\n"
                    b":irc.test 329 Bot #room 1700000000\r\n"
                    b":irc.test 332 Bot #room :Initial topic\r\n"
                    b":irc.test 333 Bot #room setter 1700000001\r\n"
                    b":Nick[!user@old.host ACCOUNT Bob\r\n"
                    b":Nick[!user@old.host AWAY gone\r\n"
                    b":Nick[!user@old.host CHGHOST newuser new.host\r\n"
                    b":irc.test MODE #room +ov Nick[ Nick[\r\n"
                    b":Nick[!newuser@new.host TOPIC #room :Changed topic\r\n"
                    b":Nick[!newuser@new.host KICK #room Guest :testing\r\n"
                    b":Nick[!newuser@new.host INVITE Guest #room\r\n"
                    b"@+typing=active :Nick[!newuser@new.host TAGMSG #room\r\n"
                    b":Nick[!newuser@new.host PRIVMSG #room :\x01ACTION waves\x01\r\n"
                    b":Nick[!newuser@new.host NOTICE Bot :notice\r\n"
                    b"@account=Bob;time=2026-08-29T01:02:05.000Z :Nick[!newuser@new.host PRIVMSG Bot :hello\r\n"
                    b":Nick[!newuser@new.host NICK :Renamed\r\n"
                    b":Renamed!newuser@new.host PART #room leaving\r\n"
                    b":Other!other@other.host QUIT gone\r\n"
                )
                await writer.drain()
                await asyncio.sleep(0.05)
            finally:
                writer.close()
                await writer.wait_closed()
                server_finished.set()

        server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        config = Config.model_validate(
            {
                "bot": {},
                "network": {
                    "server": "127.0.0.1",
                    "port": port,
                    "nick": "Bot",
                    "user": "bot",
                    "realname": "Test Bot",
                    "connect_timeout_seconds": 2,
                    "registration_timeout_seconds": 2,
                    "idle_timeout_seconds": 2,
                    "send_rate_per_second": 100,
                    "send_burst": 20,
                },
            }
        )
        logger = logging.getLogger("test.irc-integration")
        auth = AuthManager(config.auth, config.roles, logger)
        plugins = RecordingPlugins()
        client = IRCClient(
            config,
            CommandRegistry(),
            auth,
            plugins,  # type: ignore[arg-type]
            ModerationManager(),
            logger,
        )
        auth.sessions.start("Other")

        async with server:
            with pytest.raises(ConnectionError, match="server closed the connection"):
                await client._connect_once()
            await asyncio.wait_for(server_finished.wait(), timeout=2)

        assert client.network_name == "TestNet"
        assert client.casemapping == "rfc1459-strict"
        assert client.active_capabilities == {
            "account-notify",
            "account-tag",
            "away-notify",
            "chghost",
            "extended-join",
            "invite-notify",
            "message-tags",
            "multi-prefix",
            "server-time",
            "userhost-in-names",
        }
        assert plugins.messages[0]["account"] == "Bob"
        assert plugins.messages[0]["tags"]["time"] == "2026-08-29T01:02:05.000Z"
        assert plugins.messages[0]["server_time"].isoformat() == (
            "2026-08-29T01:02:05+00:00"
        )
        channel = client.state.get_channel("#ROOM")
        assert client.state.get_user("Renamed") is None
        assert client.state.get_user("Other") is None
        assert not auth.sessions.is_active("Other")
        assert channel is not None
        assert channel.names_complete
        assert not channel.members
        assert channel.flag_modes == {"n", "t"}
        assert channel.parameter_modes == {"k": "secret"}
        assert channel.created_at == 1700000000
        assert channel.topic == "Changed topic"
        assert channel.topic_setter == "Nick["
        assert channel.topic_set_at is None
        assert [name for name, _, _ in plugins.events] == [
            "JOIN",
            "ACCOUNT",
            "AWAY",
            "CHGHOST",
            "MODE",
            "TOPIC",
            "KICK",
            "INVITE",
            "TAGMSG",
            "ACTION",
            "NOTICE",
            "NICK",
            "PART",
            "QUIT",
        ]
        join_name, join_args, join_metadata = plugins.events[0]
        assert join_name == "JOIN"
        assert join_args == ("Nick[", "#room")
        assert join_metadata["account"] == "Alice"
        assert join_metadata["realname"] == "Alice Example"
        assert join_metadata["server_time"].isoformat() == ("2026-08-29T01:02:04+00:00")
        chghost_name, chghost_args, _ = plugins.events[3]
        assert chghost_name == "CHGHOST"
        assert chghost_args[:4] == (
            "Nick[",
            "Nick[!newuser@new.host",
            "Nick[!user@old.host",
            "Bob",
        )

    asyncio.run(scenario())
