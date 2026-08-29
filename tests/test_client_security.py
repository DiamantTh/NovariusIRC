from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import pytest

from novariusirc.core.auth import AuthManager
from novariusirc.core.client import IRCClient
from novariusirc.core.commands import CommandRegistry
from novariusirc.core.config import Config
from novariusirc.core.moderation import ModerationManager


class Writer:
    def __init__(self) -> None:
        self.data = bytearray()

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        return None


class SaslAuth:
    @staticmethod
    def sasl_mechanism() -> str:
        return "PLAIN"


def client() -> IRCClient:
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
    instance = IRCClient(
        config,
        commands=Any,
        auth=Any,
        plugins=Any,
        moderation=Any,
        logger=logging.getLogger("test.client"),
    )
    instance.writer = Writer()  # type: ignore[assignment]
    return instance


def test_send_raw_rejects_command_injection() -> None:
    instance = client()
    with pytest.raises(ValueError, match="CR, LF, or NUL"):
        asyncio.run(instance.send_raw("PRIVMSG #safe :hello\r\nOPER attacker"))


def test_privmsg_flattens_lines_and_respects_irc_byte_limit() -> None:
    instance = client()
    asyncio.run(instance.send_privmsg("#test", "first\nsecond " + "ä" * 400))
    payload = bytes(instance.writer.data)  # type: ignore[union-attr]
    assert payload.startswith(b"PRIVMSG #test :first second ")
    assert payload.endswith(b"\r\n")
    assert len(payload) <= 512
    payload[:-2].decode("utf-8")


def test_privmsg_rejects_invalid_target() -> None:
    instance = client()
    with pytest.raises(ValueError, match="Invalid IRC target"):
        asyncio.run(instance.send_privmsg("#safe OPER attacker", "hello"))


@pytest.mark.parametrize("channel", ["", "#one,#two", "#bad channel", ":#bad"])
def test_join_rejects_ambiguous_or_invalid_channel_arguments(channel: str) -> None:
    instance = client()
    with pytest.raises(ValueError, match="Invalid IRC channel"):
        asyncio.run(instance.join_channels([channel]))


def test_join_zero_clears_state_and_non_channel_join_is_ignored() -> None:
    instance = client()
    instance.state.join("Alice!user@host", "#test")
    asyncio.run(instance._handle_line(":bot!user@host JOIN 0"))
    assert not instance.state.channels
    assert not instance.state.users

    asyncio.run(instance._handle_line(":Alice!user@host JOIN not-a-channel"))
    assert not instance.state.channels


def test_multiline_capability_list_accepts_sasl_mechanism_values() -> None:
    instance = client()
    instance.auth = SaslAuth()  # type: ignore[assignment]
    instance.config.auth.sasl_enabled = True
    asyncio.run(
        instance._handle_cap(["bot", "LS", "*"], "account-notify sasl=EXTERNAL,PLAIN")
    )
    assert not instance.writer.data  # type: ignore[union-attr]

    asyncio.run(instance._handle_cap(["bot", "LS"], "multi-prefix"))
    payload = bytes(instance.writer.data)  # type: ignore[union-attr]
    assert payload.startswith(b"CAP REQ :sasl\r\n")
    assert b"account-notify" in payload
    assert b"multi-prefix" in payload


def test_channel_snapshot_prefers_whox_and_falls_back_to_who() -> None:
    instance = client()
    instance._active_capabilities.add("account-notify")
    instance._features.update(["bot", "WHOX"])

    asyncio.run(instance._request_channel_snapshot("#test"))
    assert bytes(instance.writer.data) == b"WHO #test %tcuhnfar,152\r\n"  # type: ignore[union-attr]

    instance.writer.data.clear()  # type: ignore[union-attr]
    instance._features.update(["bot", "-WHOX"])
    asyncio.run(instance._request_channel_snapshot("#test"))
    assert bytes(instance.writer.data) == b"WHO #test\r\n"  # type: ignore[union-attr]


def test_whox_reply_populates_identity_membership_and_away_state() -> None:
    instance = client()
    instance.state.ensure_channel("#test")
    asyncio.run(
        instance._handle_line(
            ":irc.test 354 bot 152 #test user host Nick G@ account :Real Name"
        )
    )

    user = instance.state.get_user("nick")
    channel = instance.state.get_channel("#TEST")
    assert user is not None
    assert user.hostmask == "Nick!user@host"
    assert user.account == "account"
    assert user.realname == "Real Name"
    assert user.is_away is True
    assert channel is not None
    assert channel.members[instance._features.casefold("nick")].user is user
    assert channel.members[instance._features.casefold("nick")].modes == {"o"}

    user.away = "stale away text"
    asyncio.run(instance._handle_line(":irc.test 354 bot 152 #test u h Nick H 0 :Name"))
    assert user.account is None
    assert user.is_away is False
    assert user.away is None


def test_standard_who_reply_populates_identity_and_presence() -> None:
    instance = client()
    instance.state.ensure_channel("#test")
    asyncio.run(
        instance._handle_line(
            ":irc.test 352 bot #test user host server Nick H@ :0 Real Name"
        )
    )

    user = instance.state.get_user("Nick")
    assert user is not None
    assert user.realname == "Real Name"
    assert user.is_away is False


def test_sasl_already_authenticated_is_success_and_mechanisms_are_recorded() -> None:
    instance = client()
    instance._sasl_in_progress = True
    asyncio.run(instance._handle_line(":irc.test 908 bot PLAIN,EXTERNAL :mechanisms"))
    asyncio.run(instance._handle_line(":irc.test 907 bot :already authenticated"))

    assert instance._sasl_mechanisms == {"PLAIN", "EXTERNAL"}
    assert instance._sasl_complete
    assert not instance._sasl_in_progress
    assert bytes(instance.writer.data) == b"CAP END\r\n"  # type: ignore[union-attr]


@pytest.mark.parametrize("numeric", ["432", "433", "436", "437"])
def test_registration_nickname_errors_fail_immediately(numeric: str) -> None:
    instance = client()
    with pytest.raises(ConnectionError, match=rf"\({numeric}\)"):
        asyncio.run(instance._handle_line(f":irc.test {numeric} * bot :unavailable"))


def test_server_error_ends_connection() -> None:
    instance = client()
    with pytest.raises(ConnectionError, match="Closing Link"):
        asyncio.run(instance._handle_line("ERROR :Closing Link"))


def test_required_sasl_fails_when_cap_is_unavailable_or_disabled() -> None:
    unavailable = client()
    unavailable.config.auth.sasl_enabled = True
    with pytest.raises(ConnectionError, match="does not support CAP"):
        asyncio.run(unavailable._handle_line(":irc.test 421 bot CAP :Unknown command"))

    disabled = client()
    disabled.config.auth.sasl_enabled = True
    disabled._pending_capabilities.add("sasl")
    with pytest.raises(ConnectionError, match="disabled the required SASL"):
        asyncio.run(disabled._handle_cap(["bot", "ACK"], "-sasl"))
    assert bytes(disabled.writer.data) == b"CAP END\r\n"  # type: ignore[union-attr]


def test_slow_application_hook_does_not_block_ping() -> None:
    async def scenario() -> None:
        instance = client()
        started = asyncio.Event()
        release = asyncio.Event()

        class BlockingPlugins:
            async def on_message(self, *args: object, **kwargs: object) -> None:
                started.set()
                await release.wait()

        instance.commands = CommandRegistry()
        instance.auth = AuthManager(
            instance.config.auth,
            instance.config.roles,
            logging.getLogger("test.events.auth"),
        )
        instance.moderation = ModerationManager()
        instance.plugins = BlockingPlugins()  # type: ignore[assignment]
        instance._event_queue = asyncio.Queue(maxsize=2)
        instance._event_task = asyncio.create_task(instance._event_loop())

        await instance._handle_line(":Nick!user@host PRIVMSG bot :slow")
        await asyncio.wait_for(started.wait(), timeout=1)
        await instance._handle_line("PING :still-responsive")
        assert bytes(instance.writer.data) == b"PONG :still-responsive\r\n"  # type: ignore[union-attr]

        release.set()
        await asyncio.wait_for(instance._event_queue.join(), timeout=1)
        instance._event_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await instance._event_task

    asyncio.run(scenario())
