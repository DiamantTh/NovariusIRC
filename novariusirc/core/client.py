"""Async IRC client with reconnect and basic command dispatch."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl
from itertools import cycle
from typing import Optional, Tuple

from .auth import AuthManager
from .commands import CommandContext, CommandRegistry
from .config import Config
from .logging import get_channel_logger
from .plugins import PluginManager


class IRCClient:
    def __init__(
        self,
        config: Config,
        commands: CommandRegistry,
        auth: AuthManager,
        plugins: PluginManager,
        logger: logging.Logger,
    ):
        self.config = config
        self.commands = commands
        self.auth = auth
        self.plugins = plugins
        self.logger = logger.getChild("client")
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._stop = asyncio.Event()

    async def run(self) -> None:
        base_delays = self.config.network.reconnect_delays or [10, 20, 40, 80]
        delays_cycle = cycle(base_delays)
        while not self._stop.is_set():
            delay = next(delays_cycle)
            try:
                await self._connect_once()
                delays_cycle = cycle(base_delays)
            except Exception as exc:
                self.logger.warning("Connection failed: %s", exc)
            await asyncio.sleep(max(delay, 10))

    async def stop(self) -> None:
        self._stop.set()
        if self.writer:
            self.writer.close()
            with contextlib.suppress(Exception):  # type: ignore[name-defined]
                await self.writer.wait_closed()

    async def _connect_once(self) -> None:
        host = self.config.network.server
        port = self.config.network.port
        ssl_context = None
        if self.config.network.tls:
            ssl_context = ssl.create_default_context()
        self.logger.info("Connecting to %s:%s", host, port)
        self.reader, self.writer = await asyncio.open_connection(host, port, ssl=ssl_context)
        await self._register()
        await self._listen()

    async def _register(self) -> None:
        await self.send_raw(f"NICK {self.config.network.nick}")
        await self.send_raw(f"USER {self.config.network.user} 0 * :{self.config.network.realname}")

        if self.auth.sasl_credentials():
            await self._perform_sasl()

        if self.config.network.channels:
            await self.join_channels(self.config.network.channels)

        creds = self.auth.nickserv_credentials()
        if creds:
            username, password = creds
            await self.send_privmsg(self.config.auth.nickserv_service, f"IDENTIFY {username} {password}")

    async def _listen(self) -> None:
        assert self.reader is not None
        while not self.reader.at_eof():
            raw = await self.reader.readline()
            if not raw:
                break
            line = raw.decode(errors="ignore").strip()
            await self._handle_line(line)

    async def _handle_line(self, line: str) -> None:
        self.logger.debug("<< %s", line)
        if line.startswith("PING"):
            parts = line.split()
            if len(parts) > 1:
                await self.send_raw(f"PONG {parts[1]}")
            return

        prefix, command, params, trailing = self._parse_message(line)
        if command == "001":
            self.logger.info("Connected and welcomed by server")
        if command == "PRIVMSG" and prefix:
            nick = prefix.split("!", 1)[0]
            target = params[0] if params else trailing
            message = trailing
            await self._handle_privmsg(nick, target, message)

    async def _handle_privmsg(self, nick: str, target: str, message: str) -> None:
        channel = target if target.startswith("#") else None
        if channel and self._channel_logging_enabled(channel):
            channel_logger = get_channel_logger(self.config.network.server, channel, self.config.paths)
            channel_logger.info("<%s> %s", nick, message)

        roles = self.auth.roles_for_nick(nick)
        ctx = CommandContext(
            nick=nick,
            channel=channel,
            message=message,
            config=self.config,
            client=self,
            logger=self.logger,
            roles=roles,
        )
        handled = await self.commands.dispatch(ctx)
        if not handled:
            await self.plugins.on_message(nick, channel or nick, message)

    async def send_raw(self, message: str) -> None:
        if not self.writer:
            return
        self.logger.debug(">> %s", message)
        self.writer.write((message + "\r\n").encode())
        await self.writer.drain()

    async def send_privmsg(self, target: str, message: str) -> None:
        await self.send_raw(f"PRIVMSG {target} :{message}")

    async def join_channels(self, channels: list[str]) -> None:
        for channel in channels:
            await self.send_raw(f"JOIN {channel}")

    async def _perform_sasl(self) -> None:
        payload = self.auth.sasl_plain_payload()
        if not payload:
            return
        await self.send_raw("CAP REQ :sasl")
        await self.send_raw("AUTHENTICATE PLAIN")
        await self.send_raw(f"AUTHENTICATE {payload}")
        await self.send_raw("CAP END")

    def _channel_logging_enabled(self, channel: str) -> bool:
        entries = self.config.logging.channel_logging
        for entry in entries:
            if entry.channel.lower() == channel.lower():
                return entry.enabled
        return False

    @staticmethod
    def _parse_message(line: str) -> Tuple[Optional[str], str, list[str], str]:
        prefix = None
        trailing = ""
        if line.startswith(":"):
            prefix, line = line[1:].split(" ", 1)
        if " :" in line:
            line, trailing = line.split(" :", 1)
        parts = line.split()
        command = parts.pop(0) if parts else ""
        return prefix, command, parts, trailing
