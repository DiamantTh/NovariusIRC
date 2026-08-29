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


class Reader:
    def __init__(self, *lines: bytes | ValueError) -> None:
        self.lines = list(lines)

    def at_eof(self) -> bool:
        return not self.lines

    async def readline(self) -> bytes:
        line = self.lines.pop(0)
        if isinstance(line, ValueError):
            raise line
        return line


class IdleReader:
    def at_eof(self) -> bool:
        return False

    async def readline(self) -> bytes:
        await asyncio.Event().wait()
        return b""


class SaslAuth:
    @staticmethod
    def sasl_mechanism() -> str:
        return "PLAIN"


class ChunkedSaslAuth(SaslAuth):
    @staticmethod
    def sasl_plain_payload() -> str:
        return "x" * 800


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


def test_ping_token_is_returned_unchanged() -> None:
    instance = client()
    asyncio.run(instance._handle_line("PING :opaque token with spaces"))
    assert bytes(instance.writer.data) == b"PONG :opaque token with spaces\r\n"  # type: ignore[union-attr]


def test_ctcp_ping_to_bot_is_echoed_in_notice() -> None:
    instance = client()
    asyncio.run(
        instance._handle_line(
            ":Nick!user@host PRIVMSG bot :\x01PING opaque token 123\x01"
        )
    )
    assert bytes(instance.writer.data) == (  # type: ignore[union-attr]
        b"NOTICE Nick :\x01PING opaque token 123\x01\r\n"
    )


def test_notice_respects_wire_limit_without_splitting_utf8() -> None:
    instance = client()
    asyncio.run(instance.send_notice("Nick", "ä" * 400))
    payload = bytes(instance.writer.data)  # type: ignore[union-attr]
    assert len(payload) <= 512
    payload[:-2].decode("utf-8")


def test_user_notice_cannot_trigger_server_quote_pong() -> None:
    instance = client()
    asyncio.run(
        instance._handle_quote_pong("Nick!user@host", "Please send PONG :attacker")
    )
    assert not instance.writer.data  # type: ignore[union-attr]

    asyncio.run(instance._handle_quote_pong("irc.example.test", "PONG :server-cookie"))
    assert bytes(instance.writer.data) == b"PONG :server-cookie\r\n"  # type: ignore[union-attr]


def test_idle_timeout_has_an_actionable_connection_error() -> None:
    instance = client()
    instance.config.network.idle_timeout_seconds = 0.01
    instance.reader = IdleReader()  # type: ignore[assignment]

    with pytest.raises(ConnectionError, match="received no data for 0.01 seconds"):
        asyncio.run(instance._listen())


def test_reconnect_backoff_saturates_and_resets_after_connection() -> None:
    async def scenario() -> None:
        instance = client()
        outcomes = [False, False, False, False, False, True]
        delays: list[int] = []

        async def connect_once() -> None:
            if not outcomes:
                instance._stop.set()
                return
            if not outcomes.pop(0):
                raise ConnectionError("test failure")

        async def wait_for_reconnect(delay: int) -> None:
            delays.append(delay)

        instance._connect_once = connect_once  # type: ignore[method-assign]
        instance._wait_for_reconnect = wait_for_reconnect  # type: ignore[method-assign]
        await instance.run()

        assert delays == [10, 20, 40, 80, 80, 10]

    asyncio.run(scenario())


def test_wire_limit_error_is_reported_as_connection_failure() -> None:
    instance = client()
    instance.reader = Reader(ValueError("Separator is not found"))  # type: ignore[assignment]

    with pytest.raises(ConnectionError, match="exceeds the wire limit"):
        asyncio.run(instance._listen())


def test_incomplete_final_wire_message_is_not_processed() -> None:
    instance = client()
    instance.reader = Reader(b"PING :must-not-be-processed")  # type: ignore[assignment]
    asyncio.run(instance._listen())
    assert not instance.writer.data  # type: ignore[union-attr]


def test_reconnect_discards_network_and_nickname_state() -> None:
    instance = client()
    instance.auth = AuthManager(
        instance.config.auth,
        instance.config.roles,
        logging.getLogger("test.reset.auth"),
    )
    instance.moderation = ModerationManager()
    instance._detected_network_name = "OldNetwork"
    instance._current_nick = "OldNick"
    instance._active_capabilities.add("server-time")
    instance.state.join("Someone!user@host", "#old")

    instance._reset_connection_state()

    assert instance._detected_network_name is None
    assert instance._current_nick == instance.config.network.nick
    assert not instance.active_capabilities
    assert not instance.state.channels


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


def test_welcome_is_rejected_until_required_sasl_has_completed() -> None:
    instance = client()
    instance.config.auth.sasl_enabled = True
    with pytest.raises(ConnectionError, match="before required SASL succeeded"):
        asyncio.run(instance._handle_line(":irc.test 001 bot :Welcome"))


def test_unexpected_sasl_challenge_aborts_immediately() -> None:
    instance = client()
    instance._sasl_in_progress = True
    with pytest.raises(ConnectionError, match="unsupported SASL challenge"):
        asyncio.run(instance._handle_authenticate(["unexpected"], ""))
    assert bytes(instance.writer.data) == b"AUTHENTICATE *\r\nCAP END\r\n"  # type: ignore[union-attr]


def test_sasl_plain_chunks_and_terminates_exact_400_byte_multiple() -> None:
    instance = client()
    instance.auth = ChunkedSaslAuth()  # type: ignore[assignment]
    instance._sasl_in_progress = True
    asyncio.run(instance._handle_authenticate(["+"], ""))

    lines = bytes(instance.writer.data).splitlines()  # type: ignore[union-attr]
    assert lines == [
        b"AUTHENTICATE " + b"x" * 400,
        b"AUTHENTICATE " + b"x" * 400,
        b"AUTHENTICATE +",
    ]
    assert all(len(line) <= 510 for line in lines)


def test_dynamic_cap_new_ack_and_del_updates_connection_state() -> None:
    instance = client()
    instance.config.network.ircv3_capabilities = ["away-notify"]
    instance._cap_end_sent = True

    asyncio.run(instance._handle_cap(["bot", "NEW"], "away-notify"))
    assert instance._pending_capabilities == {"away-notify"}
    assert bytes(instance.writer.data) == b"CAP REQ :away-notify\r\n"  # type: ignore[union-attr]

    asyncio.run(instance._handle_cap(["bot", "ACK"], "away-notify"))
    assert instance.active_capabilities == {"away-notify"}
    asyncio.run(instance._handle_cap(["bot", "DEL"], "away-notify"))
    assert not instance.active_capabilities
    assert "away-notify" not in instance._offered_capabilities


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
