"""Async IRC client with reconnect and basic command dispatch."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl
from pathlib import Path
from itertools import cycle
from typing import Optional, Tuple

from .auth import AuthManager
from .commands import CommandContext, CommandRegistry
from .config import Config
from .logging import get_channel_logger
from .moderation import ModerationManager
from .plugins import PluginManager


class IRCClient:
    def __init__(
        self,
        config: Config,
        commands: CommandRegistry,
        auth: AuthManager,
        plugins: PluginManager,
        moderation: ModerationManager,
        logger: logging.Logger,
    ):
        self.config = config
        self.commands = commands
        self.auth = auth
        self.plugins = plugins
        self.moderation = moderation
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
        if command == "465":
            await self._handle_kline(trailing)
            return
        if command in {"NOTICE", "ERROR"}:
            await self._handle_quote_pong(trailing)
        if command == "JOIN" and prefix:
            nick = prefix.split("!", 1)[0]
            channel = trailing or (params[0] if params else "")
            if channel:
                await self.plugins.on_join(nick, channel, hostmask=prefix)
        if command == "PART" and prefix:
            nick = prefix.split("!", 1)[0]
            channel = params[0] if params else ""
            if channel:
                await self.plugins.on_part(nick, channel, trailing, hostmask=prefix)
        if command == "QUIT" and prefix:
            nick = prefix.split("!", 1)[0]
            await self.plugins.on_quit(nick, trailing, hostmask=prefix)
        if command == "NICK" and prefix:
            old_nick = prefix.split("!", 1)[0]
            new_nick = trailing or (params[0] if params else "")
            if new_nick:
                await self.plugins.on_nick_change(old_nick, new_nick)
        if command == "PRIVMSG" and prefix:
            nick = prefix.split("!", 1)[0]
            target = params[0] if params else trailing
            message = trailing
            await self._handle_privmsg(nick, target, message, prefix=prefix)

    async def _handle_quote_pong(self, message: str) -> None:
        """Handle servers that request /QUOTE PONG :<cookie> in notices."""
        if "PONG :" in message:
            cookie = message.split("PONG :", 1)[1].strip()
            if cookie:
                await self.send_raw(f"PONG :{cookie}")
                self.logger.info("Sent quote-pong cookie")
        elif "PING :" in message:
            cookie = message.split("PING :", 1)[1].strip()
            if cookie:
                await self.send_raw(f"PONG :{cookie}")
                self.logger.info("Sent quote-pong cookie")

    async def _handle_kline(self, reason: str) -> None:
        """Handle K-line (ERR_YOUREBANNEDCREEP 465)."""
        server = self.config.network.server
        data_root = Path(self.config.paths.data_root)
        data_root.mkdir(parents=True, exist_ok=True)
        kline_file = data_root / "klines.txt"
        entry = f"{server} | {reason}\n"
        with kline_file.open("a", encoding="utf-8") as fh:
            fh.write(entry)
        self.logger.error("K-lined on %s: %s", server, reason)
        await self.stop()

    async def _handle_privmsg(self, nick: str, target: str, message: str, prefix: str = "") -> None:
        """Handle PRIVMSG with hostmask-based role resolution.
        
        Args:
            nick: Sender nickname
            target: Message target (channel or bot nick)
            message: Message content
            prefix: IRC prefix (nick!user@host) for hostmask extraction
        """
        channel = target if target.startswith("#") else None
        if channel and self._channel_logging_enabled(channel):
            channel_logger = get_channel_logger(self.config.network.server, channel, self.config.paths)
            channel_logger.info("<%s> %s", nick, message)

        if channel and nick.lower() != self.config.network.nick.lower():
            violation = await self.moderation.check_message(nick, channel, message)
            if violation:
                action, reason = violation
                command = await self.moderation.apply_action(action, nick, channel, reason)
                if command:
                    await self.send_raw(command)
                return

        # Extract hostmask from prefix (nick!user@host) or fallback to nick
        hostmask = prefix if "!" in prefix else f"{nick}!unknown@unknown"
        roles = self.auth.roles_for_hostmask(nick, hostmask)
        ctx = CommandContext(
            nick=nick,
            hostmask=hostmask,
            channel=channel,
            message=message,
            config=self.config,
            client=self,
            logger=self.logger,
            roles=roles,
        )
        handled = await self.commands.dispatch(ctx)
        if not handled:
            await self.plugins.on_message(nick, channel or nick, message, hostmask=hostmask)

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
