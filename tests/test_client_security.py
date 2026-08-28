from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from novariusirc.core.client import IRCClient
from novariusirc.core.config import Config


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


def test_multiline_capability_list_accepts_sasl_mechanism_values() -> None:
    instance = client()
    instance.auth = SaslAuth()  # type: ignore[assignment]
    asyncio.run(
        instance._handle_cap(["bot", "LS", "*"], "account-notify sasl=EXTERNAL,PLAIN")
    )
    assert not instance.writer.data  # type: ignore[union-attr]

    asyncio.run(instance._handle_cap(["bot", "LS"], "multi-prefix"))
    assert bytes(instance.writer.data) == b"CAP REQ :sasl\r\n"  # type: ignore[union-attr]
