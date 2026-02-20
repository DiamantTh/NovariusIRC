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
from .logging import get_channel_logger, get_pm_logger, get_raw_logger, strip_irc_formatting, log_channel_event, log_pm_event, log_channel_event, log_pm_event
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
        self._detected_network_name: Optional[str] = None

    @property
    def network_name(self) -> str:
        """Get network name for logging (detected from 005, config override, or server fallback)."""
        return self._detected_network_name or self.config.network.name or self.config.network.server

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
        bind_host = self.config.network.bind_ip or self.config.network.bind_hostname
        local_addr: Optional[Tuple[str, int]] = (bind_host, 0) if bind_host else None
        ssl_context = None
        if self.config.network.tls:
            ssl_context = ssl.create_default_context()
            if self.auth.certfp_ready():
                cert_file = self.config.auth.certfp_cert_file
                key_file = self.config.auth.certfp_key_file
                try:
                    ssl_context.load_cert_chain(cert_file=cert_file, keyfile=key_file)
                    self.logger.info("CertFP certificate loaded")
                except Exception as exc:
                    raise RuntimeError(f"Failed to load CertFP certificate: {exc}") from exc
        if bind_host:
            self.logger.info("Connecting to %s:%s (local bind: %s)", host, port, bind_host)
        else:
            self.logger.info("Connecting to %s:%s", host, port)
        self.reader, self.writer = await asyncio.open_connection(host, port, ssl=ssl_context, local_addr=local_addr)
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
        
        # Raw IRC logging (only when DEBUG level)
        if self.logger.isEnabledFor(logging.DEBUG):
            raw_logger = get_raw_logger(self.network_name, self.config.paths)
            raw_logger.debug("<< %s", line)
        
        if line.startswith("PING"):
            parts = line.split()
            if len(parts) > 1:
                await self.send_raw(f"PONG {parts[1]}")
            return

        prefix, command, params, trailing = self._parse_message(line)
        if command == "001":
            self.logger.info("Connected and welcomed by server")
        if command == "005":  # RPL_ISUPPORT
            # Parse NETWORK=... token
            for param in params:
                if param.startswith("NETWORK="):
                    self._detected_network_name = param.split("=", 1)[1]
                    self.logger.info("Detected network name: %s", self._detected_network_name)
                    break
        if command == "465":
            await self._handle_kline(trailing)
            return
        if command in {"NOTICE", "ERROR"}:
            await self._handle_quote_pong(trailing)
        if command == "JOIN" and prefix:
            nick = prefix.split("!", 1)[0]
            channel = trailing or (params[0] if params else "")
            if channel:
                log_channel_event(self.network_name, channel, self.config.paths, f"{nick} joins")
                await self.plugins.on_join(nick, channel, hostmask=prefix)
        if command == "PART" and prefix:
            nick = prefix.split("!", 1)[0]
            channel = params[0] if params else ""
            reason = trailing or ""
            if channel:
                if reason:
                    log_channel_event(self.network_name, channel, self.config.paths, f"{nick} parts ({reason})")
                else:
                    log_channel_event(self.network_name, channel, self.config.paths, f"{nick} parts")
                await self.plugins.on_part(nick, channel, reason, hostmask=prefix)
        if command == "QUIT" and prefix:
            nick = prefix.split("!", 1)[0]
            reason = trailing or ""
            # Log QUIT in all channels and PMs
            for channel_name in self.config.network.channels:
                if self._channel_logging_enabled(channel_name):
                    if reason:
                        log_channel_event(self.network_name, channel_name, self.config.paths, f"{nick} quits ({reason})")
                    else:
                        log_channel_event(self.network_name, channel_name, self.config.paths, f"{nick} quits")
            # Also log in PM log if there's been recent PM activity
            if reason:
                log_pm_event(self.network_name, nick, self.config.paths, f"{nick} quits ({reason})")
            else:
                log_pm_event(self.network_name, nick, self.config.paths, f"{nick} quits")
            await self.plugins.on_quit(nick, reason, hostmask=prefix)
        if command == "NICK" and prefix:
            old_nick = prefix.split("!", 1)[0]
            new_nick = trailing or (params[0] if params else "")
            if new_nick:
                # Log in all active channels
                for channel_name in self.config.network.channels:
                    if self._channel_logging_enabled(channel_name):
                        log_channel_event(self.network_name, channel_name, self.config.paths, f"{old_nick} is now known as {new_nick}")
                await self.plugins.on_nick_change(old_nick, new_nick)
        if command == "KICK" and prefix:
            kicker = prefix.split("!", 1)[0]
            channel = params[0] if len(params) > 0 else ""
            kicked = params[1] if len(params) > 1 else ""
            reason = trailing or ""
            if channel:
                if reason:
                    log_channel_event(self.network_name, channel, self.config.paths, f"{kicker} kicks {kicked} ({reason})")
                else:
                    log_channel_event(self.network_name, channel, self.config.paths, f"{kicker} kicks {kicked}")
        if command == "MODE" and prefix:
            mode_setter = prefix.split("!", 1)[0]
            channel = params[0] if params else ""
            mode_str = params[1] if len(params) > 1 else ""
            mode_args = " ".join(params[2:]) if len(params) > 2 else ""
            if channel.startswith("#"):
                if mode_args:
                    log_channel_event(self.network_name, channel, self.config.paths, f"{mode_setter} sets mode {mode_str} {mode_args}")
                else:
                    log_channel_event(self.network_name, channel, self.config.paths, f"{mode_setter} sets mode {mode_str}")
        if command == "TOPIC" and prefix:
            topic_setter = prefix.split("!", 1)[0]
            channel = params[0] if params else ""
            topic = trailing or ""
            if channel:
                if topic:
                    log_channel_event(self.network_name, channel, self.config.paths, f'{topic_setter} sets topic to "{topic}"')
                else:
                    log_channel_event(self.network_name, channel, self.config.paths, f"{topic_setter} unsets topic")
        if command == "PRIVMSG" and prefix:
            nick = prefix.split("!", 1)[0]
            target = params[0] if params else trailing
            message = trailing
            # Handle ACTION (\x01ACTION ...\x01)
            if message.startswith("\x01ACTION ") and message.endswith("\x01"):
                action_text = message[8:-1]  # Strip \x01ACTION and \x01
                await self._handle_action(nick, target, action_text, prefix=prefix)
            else:
                await self._handle_privmsg(nick, target, message, prefix=prefix)
        if command == "NOTICE" and prefix:
            nick = prefix.split("!", 1)[0]
            target = params[0] if params else trailing
            message = trailing
            await self._handle_notice(nick, target, message)

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
        is_pm = target.lower() == self.config.network.nick.lower()
        
        # Log channel messages
        if channel and self._channel_logging_enabled(channel):
            channel_logger = get_channel_logger(self.network_name, channel, self.config.paths)
            clean_message = strip_irc_formatting(message)
            channel_logger.info("<%s> %s", nick, clean_message)
        
        # Log private messages
        if is_pm:
            pm_logger = get_pm_logger(self.network_name, nick, self.config.paths)
            clean_message = strip_irc_formatting(message)
            pm_logger.info("<%s> %s", nick, clean_message)

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

    async def _handle_action(self, nick: str, target: str, action_text: str, prefix: str = "") -> None:
        """Handle ACTION (\x01ACTION ...\x01).
        
        Args:
            nick: Sender nickname
            target: Message target (channel or bot nick)
            action_text: Action text (without \x01 markers)
            prefix: IRC prefix (nick!user@host)
        """
        channel = target if target.startswith("#") else None
        is_pm = target.lower() == self.config.network.nick.lower()
        
        # Log channel actions
        if channel and self._channel_logging_enabled(channel):
            channel_logger = get_channel_logger(self.network_name, channel, self.config.paths)
            clean_text = strip_irc_formatting(action_text)
            channel_logger.info("* %s %s", nick, clean_text)
        
        # Log PM actions
        if is_pm:
            pm_logger = get_pm_logger(self.network_name, nick, self.config.paths)
            clean_text = strip_irc_formatting(action_text)
            pm_logger.info("* %s %s", nick, clean_text)

    async def _handle_notice(self, nick: str, target: str, message: str) -> None:
        """Handle NOTICE messages (channel or PM).
        
        Args:
            nick: Sender nickname (or server name)
            target: Message target (channel or bot nick)
            message: Notice content
        """
        channel = target if target.startswith("#") else None
        is_pm = target.lower() == self.config.network.nick.lower()
        
        # Log channel notices
        if channel and self._channel_logging_enabled(channel):
            channel_logger = get_channel_logger(self.network_name, channel, self.config.paths)
            clean_message = strip_irc_formatting(message)
            channel_logger.info("--%s-- %s", nick, clean_message)
        
        # Log PM notices (NickServ, ChanServ, etc.)
        if is_pm:
            pm_logger = get_pm_logger(self.network_name, nick, self.config.paths)
            clean_message = strip_irc_formatting(message)
            pm_logger.info("--%s-- %s", nick, clean_message)

    async def send_raw(self, message: str) -> None:
        if not self.writer:
            return
        self.logger.debug(">> %s", message)
        
        # Raw IRC logging (only when DEBUG level)
        if self.logger.isEnabledFor(logging.DEBUG):
            raw_logger = get_raw_logger(self.network_name, self.config.paths)
            raw_logger.debug(">> %s", message)
        
        self.writer.write((message + "\r\n").encode())
        await self.writer.drain()

    async def send_privmsg(self, target: str, message: str) -> None:
        await self.send_raw(f"PRIVMSG {target} :{message}")

    async def join_channels(self, channels: list[str]) -> None:
        for channel in channels:
            await self.send_raw(f"JOIN {channel}")

    async def _perform_sasl(self) -> None:
        mechanism = self.auth.sasl_mechanism()
        await self.send_raw("CAP REQ :sasl")
        if mechanism == "EXTERNAL":
            await self.send_raw("AUTHENTICATE EXTERNAL")
            await self.send_raw("AUTHENTICATE +")
            await self.send_raw("CAP END")
            return

        payload = self.auth.sasl_plain_payload()
        if not payload:
            await self.send_raw("CAP END")
            return

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
