"""Async IRC client with reconnect and basic command dispatch."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl
import time
from collections.abc import Coroutine
from datetime import datetime
from itertools import cycle
from pathlib import Path

from .auth import AuthManager
from .commands import CommandContext, CommandRegistry
from .config import Config
from .logging import (
    get_channel_logger,
    get_pm_logger,
    get_raw_logger,
    log_channel_event,
    log_pm_event,
    strip_irc_formatting,
)
from .moderation import ModerationManager
from .plugins import PluginManager
from .protocol import (
    CASEMAPPINGS,
    IRCFeatures,
    IRCMessage,
    parse_message,
    parse_server_time,
)
from .state import IRCState, normalize_account, split_source

_SEND_NORMAL = 10
_SEND_PRIORITY = 0
_MAX_INCOMING_BYTES = 8703  # 8191 bytes of tags plus a 512-byte IRC message.


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
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._stop = asyncio.Event()
        self._detected_network_name: str | None = None
        self._current_nick = config.network.nick
        self._registration_complete = False
        self._registration_event = asyncio.Event()
        self._sasl_in_progress = False
        self._sasl_complete = False
        self._features = IRCFeatures()
        self.state = IRCState(self._features)
        self._offered_capabilities: dict[str, str | None] = {}
        self._active_capabilities: set[str] = set()
        self._pending_capabilities: set[str] = set()
        self._sasl_mechanisms: set[str] = set()
        self._cap_end_sent = False
        self._send_queue: (
            asyncio.PriorityQueue[tuple[int, int, str, bool, asyncio.Future[None]]]
            | None
        ) = None
        self._send_sequence = 0
        self._sender_task: asyncio.Task[None] | None = None
        self._event_queue: (
            asyncio.Queue[tuple[str, Coroutine[object, object, None]]] | None
        ) = None
        self._event_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()

    @property
    def network_name(self) -> str:
        """Get the detected, configured, or fallback network name for logging."""
        return (
            self._detected_network_name
            or self.config.network.name
            or self.config.network.server
        )

    @property
    def active_capabilities(self) -> frozenset[str]:
        return frozenset(self._active_capabilities)

    @property
    def casemapping(self) -> str:
        return self._features.casemapping

    async def run(self) -> None:
        base_delays = self.config.network.reconnect_delays or [10, 20, 40, 80]
        delays_cycle = cycle(base_delays)
        while not self._stop.is_set():
            delay = next(delays_cycle)
            try:
                await self._connect_once()
                delays_cycle = cycle(base_delays)
            except Exception as exc:  # noqa: BLE001 - reconnect is the process boundary
                self.logger.warning("Connection failed: %s", exc)
            if self._stop.is_set():
                break
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=delay)

    async def stop(self) -> None:
        self._stop.set()
        writer = self.writer
        if writer:
            if not writer.is_closing():
                with contextlib.suppress(
                    asyncio.TimeoutError, ConnectionError, OSError, RuntimeError
                ):
                    await asyncio.wait_for(
                        self.send_raw("QUIT :NovariusIRC shutting down", priority=True),
                        timeout=2.0,
                    )
            writer.close()
            with contextlib.suppress(ConnectionError, OSError, RuntimeError):
                await writer.wait_closed()

    async def _connect_once(self) -> None:
        host = self.config.network.server
        port = self.config.network.port
        bind_host = self.config.network.bind_ip or self.config.network.bind_hostname
        local_addr: tuple[str, int] | None = (bind_host, 0) if bind_host else None
        ssl_context = None
        if self.config.network.tls:
            ssl_context = ssl.create_default_context()
            if self.auth.certfp_ready():
                cert_file = self.config.auth.certfp_cert_file
                key_file = self.config.auth.certfp_key_file
                try:
                    ssl_context.load_cert_chain(cert_file=cert_file, keyfile=key_file)
                    self.logger.info("CertFP certificate loaded")
                except (OSError, ssl.SSLError) as exc:
                    raise RuntimeError(
                        f"Failed to load CertFP certificate: {exc}"
                    ) from exc
        if bind_host:
            self.logger.info(
                "Connecting to %s:%s (local bind: %s)", host, port, bind_host
            )
        else:
            self.logger.info("Connecting to %s:%s", host, port)
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(
                host,
                port,
                ssl=ssl_context,
                local_addr=local_addr,
                limit=_MAX_INCOMING_BYTES,
            ),
            timeout=self.config.network.connect_timeout_seconds,
        )
        self._registration_complete = False
        self._registration_event.clear()
        self._sasl_in_progress = False
        self._sasl_complete = False
        self._features = IRCFeatures()
        self.state = IRCState(self._features)
        self.auth.set_casefold(self._features.casefold)
        self.moderation.set_casefold(self._features.casefold)
        self._offered_capabilities.clear()
        self._active_capabilities.clear()
        self._pending_capabilities.clear()
        self._sasl_mechanisms.clear()
        self._cap_end_sent = False
        self._send_queue = asyncio.PriorityQueue(
            maxsize=self.config.network.send_queue_size
        )
        self._sender_task = asyncio.create_task(
            self._send_loop(), name="irc-send-queue"
        )
        self._event_queue = asyncio.Queue(maxsize=self.config.network.event_queue_size)
        self._event_task = asyncio.create_task(
            self._event_loop(), name="irc-application-events"
        )
        listen_task: asyncio.Task[None] | None = None
        registration_task: asyncio.Task[bool] | None = None
        try:
            await self._register()
            listen_task = asyncio.create_task(self._listen(), name="irc-reader")
            registration_task = asyncio.create_task(
                self._registration_event.wait(), name="irc-registration"
            )
            done, _ = await asyncio.wait(
                {listen_task, registration_task},
                timeout=self.config.network.registration_timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if registration_task not in done:
                if listen_task in done:
                    await listen_task
                    raise ConnectionError("Connection closed before IRC registration")
                raise TimeoutError("IRC registration timed out")
            registration_task.result()
            await listen_task
        finally:
            if registration_task and not registration_task.done():
                registration_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await registration_task
            if listen_task and not listen_task.done():
                listen_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await listen_task
            if self._event_task:
                self._event_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._event_task
            self._close_event_queue()
            self._event_task = None
            self._event_queue = None
            if self._sender_task:
                self._sender_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, ConnectionError):
                    await self._sender_task
            self._fail_send_queue(ConnectionError("IRC connection closed"))
            self._sender_task = None
            self._send_queue = None
            if self.writer:
                self.writer.close()
                with contextlib.suppress(ConnectionError, OSError, RuntimeError):
                    await self.writer.wait_closed()
            self.reader = None
            self.writer = None

    async def _register(self) -> None:
        if self.config.network.ircv3_enabled or self.config.auth.sasl_enabled:
            await self.send_raw("CAP LS 302", priority=True)
        await self.send_raw(f"NICK {self.config.network.nick}", priority=True)
        await self.send_raw(
            f"USER {self.config.network.user} 0 * :{self.config.network.realname}",
            priority=True,
        )

    async def _listen(self) -> None:
        assert self.reader is not None
        while not self.reader.at_eof():
            raw = await asyncio.wait_for(
                self.reader.readline(),
                timeout=self.config.network.idle_timeout_seconds,
            )
            if not raw:
                break
            if len(raw) > _MAX_INCOMING_BYTES:
                self.logger.warning(
                    "Ignoring oversized IRC message (%d bytes)", len(raw)
                )
                continue
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            await self._handle_line(line)

    async def _handle_line(self, line: str) -> None:
        self.logger.debug("<< %s", line)

        # Raw IRC logging (only when DEBUG level)
        if self.logger.isEnabledFor(logging.DEBUG):
            raw_logger = get_raw_logger(self.network_name, self.config.paths)
            raw_logger.debug("<< %s", line)

        try:
            parsed = parse_message(line)
        except ValueError as exc:
            self.logger.warning("Ignoring malformed IRC message: %s", exc)
            return

        prefix = parsed.prefix
        command = parsed.command
        params = list(parsed.params)
        trailing = parsed.trailing or ""
        server_time = parse_server_time(parsed.tags.get("time"))
        if "time" in parsed.tags and server_time is None:
            self.logger.warning("Ignoring invalid IRCv3 server-time tag")
        source_user = None
        if prefix and "!" in prefix:
            source_nick, _, _ = split_source(prefix)
            source_user = self.state.ensure_user(source_nick, prefix)
            if "account" in parsed.tags:
                source_user = self.state.set_account(prefix, parsed.tags.get("account"))
        if command == "PING":
            cookie = trailing or (params[0] if params else "")
            if cookie:
                await self.send_raw(f"PONG :{cookie}", priority=True)
            return
        if command == "CAP":
            await self._handle_cap(params, trailing)
            return
        if command == "AUTHENTICATE":
            await self._handle_authenticate(params, trailing)
            return
        if command in {"903", "907"}:
            if command == "907":
                self.logger.info("Server reports an already authenticated SASL session")
            else:
                self.logger.info("SASL authentication succeeded")
            self._sasl_in_progress = False
            self._sasl_complete = True
            await self._maybe_end_cap_negotiation()
            return
        if command == "908" and len(params) >= 2:
            self._sasl_mechanisms.update(
                mechanism.upper() for mechanism in params[1].split(",") if mechanism
            )
            return
        if command in {"902", "904", "905", "906"}:
            self.logger.error("SASL authentication failed: %s", trailing or command)
            self._sasl_in_progress = False
            await self._end_cap_negotiation()
            raise ConnectionError("SASL authentication failed")
        if command == "001":
            self.logger.info("Connected and welcomed by server")
            if params:
                self._current_nick = params[0]
            await self._after_welcome()
        if command == "005":  # RPL_ISUPPORT
            previous_mapping = self._features.casemapping
            previous_prefix = (
                self._features.prefix_modes,
                self._features.prefix_symbols,
            )
            previous_chanmodes = self._features.chanmodes
            self._features.update(params)
            advertised_mapping = self._features.tokens.get("CASEMAPPING")
            if advertised_mapping and advertised_mapping not in CASEMAPPINGS:
                self.logger.warning(
                    "Unsupported CASEMAPPING %r; continuing with %s",
                    advertised_mapping,
                    self._features.casemapping,
                )
            if self._features.network:
                self._detected_network_name = self._features.network
            if self._features.casemapping != previous_mapping:
                self.logger.info(
                    "Server CASEMAPPING changed from %s to %s",
                    previous_mapping,
                    self._features.casemapping,
                )
                self.auth.set_casefold(self._features.casefold)
                self.moderation.set_casefold(self._features.casefold)
                self.state.reindex()
            current_prefix = (
                self._features.prefix_modes,
                self._features.prefix_symbols,
            )
            if current_prefix != previous_prefix:
                self.state.prune_membership_modes()
            if self._features.chanmodes != previous_chanmodes:
                self.state.clear_channel_modes()
        if command == "465":
            await self._handle_kline(trailing)
            return
        if command == "NOTICE":
            await self._handle_quote_pong(trailing)
        if command == "ERROR":
            raise ConnectionError(trailing or "IRC server closed the connection")
        if (
            command == "421"
            and len(params) >= 2
            and params[1].upper() == "CAP"
            and self.config.auth.sasl_enabled
        ):
            raise ConnectionError("Server does not support CAP required for SASL")
        if command in {"432", "433", "436", "437"} and not self._registration_complete:
            detail = trailing or "nickname rejected during registration"
            raise ConnectionError(
                f"IRC nickname registration failed ({command}): {detail}"
            )
        if command in {"471", "473", "474", "475", "476", "477"}:
            channel = params[1] if len(params) >= 2 else ""
            if self._features.is_channel(channel):
                self.logger.warning(
                    "Could not join %s: %s", channel, trailing or command
                )
            return
        if command == "JOIN" and prefix:
            nick, _, _ = split_source(prefix)
            channel = params[0] if params else self._text_parameter(parsed, 0)
            if channel == "0":
                if self._same_identifier(nick, self._current_nick):
                    self.state.clear()
                return
            if not self._features.is_channel(channel):
                self.logger.warning(
                    "Ignoring JOIN for invalid channel target %r", channel
                )
                return
            extended = "extended-join" in self._active_capabilities
            account = (
                normalize_account(params[1]) if extended and len(params) > 1 else None
            )
            if account is None and source_user:
                account = source_user.account
            realname = (
                self._text_parameter(parsed, 2)
                if extended and len(params) > 1
                else None
            )
            joined_user = self.state.join(
                prefix,
                channel,
                account=params[1] if extended and len(params) > 1 else None,
                realname=realname,
            ).user
            log_channel_event(
                self.network_name, channel, self.config.paths, f"{nick} joins"
            )
            await self._dispatch_application(
                "JOIN",
                self.plugins.on_join(
                    nick,
                    channel,
                    hostmask=joined_user.hostmask,
                    account=joined_user.account,
                    realname=joined_user.realname,
                    tags=parsed.tags,
                    server_time=server_time,
                ),
            )
            if self._same_identifier(nick, self._current_nick):
                await self._request_channel_snapshot(channel)
        if command == "PART" and prefix:
            nick, _, _ = split_source(prefix)
            channel = params[0] if params else ""
            reason = self._text_parameter(parsed, 1)
            if self._features.is_channel(channel):
                if reason:
                    log_channel_event(
                        self.network_name,
                        channel,
                        self.config.paths,
                        f"{nick} parts ({reason})",
                    )
                else:
                    log_channel_event(
                        self.network_name, channel, self.config.paths, f"{nick} parts"
                    )
                await self._dispatch_application(
                    "PART",
                    self.plugins.on_part(
                        nick,
                        channel,
                        reason,
                        hostmask=prefix,
                        account=source_user.account if source_user else None,
                        tags=parsed.tags,
                        server_time=server_time,
                    ),
                )
                if self._same_identifier(nick, self._current_nick):
                    self.state.remove_channel(channel)
                else:
                    self.state.part(nick, channel)
        if command == "QUIT" and prefix:
            nick, _, _ = split_source(prefix)
            reason = self._text_parameter(parsed, 0)
            channels = self.state.channels_for(nick)
            # Before the first NAMES burst, fall back to configured channels.
            log_channels = channels or self.config.network.channels
            for channel_name in log_channels:
                if self._channel_logging_enabled(channel_name):
                    if reason:
                        log_channel_event(
                            self.network_name,
                            channel_name,
                            self.config.paths,
                            f"{nick} quits ({reason})",
                        )
                    else:
                        log_channel_event(
                            self.network_name,
                            channel_name,
                            self.config.paths,
                            f"{nick} quits",
                        )
            # Also log in PM log if there's been recent PM activity
            if reason:
                log_pm_event(
                    self.network_name,
                    nick,
                    self.config.paths,
                    f"{nick} quits ({reason})",
                )
            else:
                log_pm_event(
                    self.network_name, nick, self.config.paths, f"{nick} quits"
                )
            await self._dispatch_application(
                "QUIT",
                self.plugins.on_quit(
                    nick,
                    reason,
                    hostmask=prefix,
                    account=source_user.account if source_user else None,
                    tags=parsed.tags,
                    server_time=server_time,
                    channels=channels,
                ),
            )
            self.auth.end_totp_session(nick)
            self.state.quit(nick)
        if command == "NICK" and prefix:
            old_nick, _, _ = split_source(prefix)
            new_nick = trailing or (params[0] if params else "")
            if new_nick:
                channels = self.state.channels_for(old_nick)
                if self._same_identifier(old_nick, self._current_nick):
                    self._current_nick = new_nick
                self.auth.rename_nick(old_nick, new_nick)
                self.moderation.rename_user(old_nick, new_nick)
                renamed_user = self.state.rename(old_nick, new_nick, prefix)
                # Log in all active channels
                for channel_name in channels or self.config.network.channels:
                    if self._channel_logging_enabled(channel_name):
                        log_channel_event(
                            self.network_name,
                            channel_name,
                            self.config.paths,
                            f"{old_nick} is now known as {new_nick}",
                        )
                await self._dispatch_application(
                    "NICK",
                    self.plugins.on_nick_change(
                        old_nick,
                        new_nick,
                        hostmask=renamed_user.hostmask,
                        account=renamed_user.account,
                        tags=parsed.tags,
                        server_time=server_time,
                        channels=channels,
                    ),
                )
        if command == "KICK" and prefix:
            kicker = prefix.split("!", 1)[0]
            channel = params[0] if len(params) > 0 else ""
            kicked = params[1] if len(params) > 1 else ""
            reason = self._text_parameter(parsed, 2)
            if self._features.is_channel(channel):
                if reason:
                    log_channel_event(
                        self.network_name,
                        channel,
                        self.config.paths,
                        f"{kicker} kicks {kicked} ({reason})",
                    )
                else:
                    log_channel_event(
                        self.network_name,
                        channel,
                        self.config.paths,
                        f"{kicker} kicks {kicked}",
                    )
                await self._dispatch_application(
                    "KICK",
                    self.plugins.on_kick(
                        kicker,
                        channel,
                        kicked,
                        reason,
                        prefix,
                        source_user.account if source_user else None,
                        parsed.tags,
                        server_time,
                    ),
                )
                if self._same_identifier(kicked, self._current_nick):
                    self.state.remove_channel(channel)
                else:
                    self.state.part(kicked, channel)
        if command == "MODE" and prefix:
            mode_setter = prefix.split("!", 1)[0]
            channel = params[0] if params else ""
            mode_str = params[1] if len(params) > 1 else ""
            mode_args = " ".join(params[2:]) if len(params) > 2 else ""
            if self._features.is_channel(channel):
                self._apply_channel_modes(channel, mode_str, params[2:])
                if mode_args:
                    log_channel_event(
                        self.network_name,
                        channel,
                        self.config.paths,
                        f"{mode_setter} sets mode {mode_str} {mode_args}",
                    )
                else:
                    log_channel_event(
                        self.network_name,
                        channel,
                        self.config.paths,
                        f"{mode_setter} sets mode {mode_str}",
                    )
                await self._dispatch_application(
                    "MODE",
                    self.plugins.on_mode(
                        mode_setter,
                        channel,
                        mode_str,
                        params[2:],
                        prefix,
                        source_user.account if source_user else None,
                        parsed.tags,
                        server_time,
                    ),
                )
        if command == "TOPIC" and prefix:
            topic_setter = prefix.split("!", 1)[0]
            channel = params[0] if params else ""
            topic = self._text_parameter(parsed, 1)
            if self._features.is_channel(channel):
                channel_state = self.state.ensure_channel(channel)
                channel_state.topic = topic or None
                channel_state.topic_setter = topic_setter
                channel_state.topic_set_at = (
                    int(server_time.timestamp()) if server_time else None
                )
                if topic:
                    log_channel_event(
                        self.network_name,
                        channel,
                        self.config.paths,
                        f'{topic_setter} sets topic to "{topic}"',
                    )
                else:
                    log_channel_event(
                        self.network_name,
                        channel,
                        self.config.paths,
                        f"{topic_setter} unsets topic",
                    )
                await self._dispatch_application(
                    "TOPIC",
                    self.plugins.on_topic(
                        topic_setter,
                        channel,
                        topic,
                        prefix,
                        source_user.account if source_user else None,
                        parsed.tags,
                        server_time,
                    ),
                )
        if command == "353" and len(params) >= 3:
            channel = params[2]
            if self._features.is_channel(channel) and self.state.get_channel(channel):
                self.state.add_names(channel, self._text_parameter(parsed, 3))
        if command == "366" and len(params) >= 2:
            channel = params[1]
            if self._features.is_channel(channel) and self.state.get_channel(channel):
                self.state.finish_names(channel)
        if command == "324" and len(params) >= 3:
            channel_state = self.state.ensure_channel(params[1])
            channel_state.list_modes.clear()
            channel_state.parameter_modes.clear()
            channel_state.flag_modes.clear()
            self._apply_channel_modes(params[1], params[2], params[3:])
        if command == "329" and len(params) >= 3:
            with contextlib.suppress(ValueError):
                self.state.ensure_channel(params[1]).created_at = int(params[2])
        if command == "331" and len(params) >= 2:
            channel_state = self.state.ensure_channel(params[1])
            channel_state.topic = None
            channel_state.topic_setter = None
            channel_state.topic_set_at = None
        if command == "332" and len(params) >= 2:
            self.state.ensure_channel(params[1]).topic = self._text_parameter(parsed, 2)
        if command == "333" and len(params) >= 4:
            channel_state = self.state.ensure_channel(params[1])
            channel_state.topic_setter = params[2]
            with contextlib.suppress(ValueError):
                channel_state.topic_set_at = int(params[3])
        if command == "352" and len(params) >= 7:
            # RPL_WHOREPLY: client, channel, user, host, server, nick, flags
            channel, username, hostname = params[1], params[2], params[3]
            nick, flags = params[5], params[6]
            realname = trailing.partition(" ")[2] or None
            self._update_who_state(
                channel,
                username,
                hostname,
                nick,
                flags,
                realname=realname,
            )
        if command == "354" and len(params) >= 8 and params[1] == "152":
            # Our WHOX fields are: token, channel, user, host, nick, flags,
            # account, realname. The first parameter remains the client nick.
            self._update_who_state(
                params[2],
                params[3],
                params[4],
                params[5],
                params[6],
                account=params[7],
                realname=trailing or None,
            )
        if command == "ACCOUNT" and prefix:
            account_value = params[0] if params else trailing
            user = self.state.set_account(prefix, account_value)
            await self._dispatch_application(
                "ACCOUNT",
                self.plugins.on_account(
                    user.nick,
                    user.account,
                    user.hostmask,
                    parsed.tags,
                    server_time,
                ),
            )
        if command == "AWAY" and prefix:
            away_message = (
                self._text_parameter(parsed, 0)
                if parsed.trailing is not None or params
                else None
            )
            user = self.state.set_away(prefix, away_message)
            await self._dispatch_application(
                "AWAY",
                self.plugins.on_away(
                    user.nick,
                    user.away,
                    user.hostmask,
                    user.account,
                    parsed.tags,
                    server_time,
                ),
            )
        if command == "CHGHOST" and prefix and len(params) >= 2:
            old_hostmask = prefix
            user = self.state.change_host(prefix, params[0], params[1])
            await self._dispatch_application(
                "CHGHOST",
                self.plugins.on_chghost(
                    user.nick,
                    user.hostmask,
                    old_hostmask,
                    user.account,
                    parsed.tags,
                    server_time,
                ),
            )
        if command == "INVITE" and prefix and len(params) >= 2:
            inviter, _, _ = split_source(prefix)
            await self._dispatch_application(
                "INVITE",
                self.plugins.on_invite(
                    inviter,
                    params[0],
                    params[1],
                    prefix,
                    source_user.account if source_user else None,
                    parsed.tags,
                    server_time,
                ),
            )
        if command == "TAGMSG" and prefix and params:
            sender, _, _ = split_source(prefix)
            await self._dispatch_application(
                "TAGMSG",
                self.plugins.on_tagmsg(
                    sender,
                    params[0],
                    self._features.channel_from_target(params[0]),
                    prefix,
                    source_user.account if source_user else None,
                    parsed.tags,
                    server_time,
                ),
            )
        if command == "PRIVMSG" and prefix:
            nick = prefix.split("!", 1)[0]
            target = params[0] if params else ""
            message = self._text_parameter(parsed, 1)
            # Handle ACTION (\x01ACTION ...\x01)
            if message.startswith("\x01ACTION ") and message.endswith("\x01"):
                action_text = message[8:-1]  # Strip \x01ACTION and \x01
                await self._dispatch_application(
                    "ACTION",
                    self._handle_action(
                        nick,
                        target,
                        action_text,
                        prefix=prefix,
                        tags=parsed.tags,
                        server_time=server_time,
                        account=source_user.account if source_user else None,
                    ),
                )
            else:
                await self._dispatch_application(
                    "PRIVMSG",
                    self._handle_privmsg(
                        nick,
                        target,
                        message,
                        prefix=prefix,
                        tags=parsed.tags,
                        server_time=server_time,
                        account=source_user.account if source_user else None,
                    ),
                )
        if command == "NOTICE" and prefix:
            nick = prefix.split("!", 1)[0]
            target = params[0] if params else ""
            message = self._text_parameter(parsed, 1)
            await self._dispatch_application(
                "NOTICE",
                self._handle_notice(
                    nick,
                    target,
                    message,
                    prefix=prefix,
                    tags=parsed.tags,
                    server_time=server_time,
                    account=source_user.account if source_user else None,
                ),
            )

    async def _handle_quote_pong(self, message: str) -> None:
        """Handle servers that request /QUOTE PONG :<cookie> in notices."""
        if "PONG :" in message:
            cookie = message.split("PONG :", 1)[1].strip()
            if cookie:
                await self.send_raw(f"PONG :{cookie}", priority=True)
                self.logger.info("Sent quote-pong cookie")
        elif "PING :" in message:
            cookie = message.split("PING :", 1)[1].strip()
            if cookie:
                await self.send_raw(f"PONG :{cookie}", priority=True)
                self.logger.info("Sent quote-pong cookie")

    def _apply_channel_modes(
        self, channel: str, mode_string: str, arguments: list[str]
    ) -> None:
        channel_state = self.state.ensure_channel(channel)
        type_a, type_b, type_c, _ = self._features.chanmodes
        adding = True
        argument_index = 0
        for mode in mode_string:
            if mode == "+":
                adding = True
                continue
            if mode == "-":
                adding = False
                continue
            takes_parameter = self._features.mode_takes_parameter(mode, adding)
            argument = None
            if takes_parameter:
                if argument_index >= len(arguments):
                    self.logger.warning(
                        "MODE %s %s is missing an argument for %s",
                        channel,
                        mode_string,
                        mode,
                    )
                    break
                argument = arguments[argument_index]
                argument_index += 1
            if mode in self._features.prefix_modes and argument:
                self.state.set_membership_mode(channel, argument, mode, adding)
            elif mode in type_a and argument:
                values = channel_state.list_modes.setdefault(mode, set())
                if adding:
                    values.add(argument)
                else:
                    values.discard(argument)
                    if not values:
                        channel_state.list_modes.pop(mode, None)
            elif mode in type_b and argument:
                if adding:
                    channel_state.parameter_modes[mode] = argument
                else:
                    channel_state.parameter_modes.pop(mode, None)
            elif mode in type_c:
                if adding and argument:
                    channel_state.parameter_modes[mode] = argument
                elif not adding:
                    channel_state.parameter_modes.pop(mode, None)
            elif adding:
                channel_state.flag_modes.add(mode)
            else:
                channel_state.flag_modes.discard(mode)

    async def _request_channel_snapshot(self, channel: str) -> None:
        """Request identity and presence state after this client joins a channel."""
        if not ({"account-notify", "away-notify"} & self._active_capabilities):
            return
        if "WHOX" in self._features.tokens:
            # A fixed query token makes RPL_WHOSPCRPL safe to distinguish from
            # WHOX requests made by plugins or users.
            await self.send_raw(f"WHO {channel} %tcuhnfar,152")
        else:
            await self.send_raw(f"WHO {channel}")

    def _update_who_state(
        self,
        channel: str,
        username: str,
        hostname: str,
        nick: str,
        flags: str,
        *,
        account: str | None = None,
        realname: str | None = None,
    ) -> None:
        # Standard WHO replies have no correlation token. Only merge replies
        # into channels the client already knows it joined.
        if self.state.get_channel(channel) is None:
            return
        membership = self.state.join(
            f"{nick}!{username}@{hostname}",
            channel,
            account=None if account in {None, "0"} else account,
            realname=realname,
        )
        if account == "0":
            membership.user.account = None
        self.state.set_away_status(membership.user.nick, "G" in flags)
        for prefix_symbol in self._features.prefix_symbols:
            mode = self._features.mode_for_prefix(prefix_symbol)
            if mode and prefix_symbol in flags:
                membership.modes.add(mode)

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

    async def _handle_privmsg(
        self,
        nick: str,
        target: str,
        message: str,
        prefix: str = "",
        tags: dict[str, str | None] | None = None,
        server_time: datetime | None = None,
        account: str | None = None,
    ) -> None:
        """Handle PRIVMSG with hostmask-based role resolution.

        Args:
            nick: Sender nickname
            target: Message target (channel or bot nick)
            message: Message content
            prefix: IRC prefix (nick!user@host) for hostmask extraction
        """
        channel = self._features.channel_from_target(target)
        is_pm = self._same_identifier(target, self._current_nick)
        message_tags = dict(tags or {})
        sender_user = self.state.ensure_user(nick, prefix)
        if "account" in message_tags:
            sender_user.account = normalize_account(message_tags.get("account"))
        elif account is not None:
            sender_user.account = account
        account = sender_user.account

        # Log channel messages
        if channel and self._channel_logging_enabled(channel):
            channel_logger = get_channel_logger(
                self.network_name, channel, self.config.paths
            )
            clean_message = strip_irc_formatting(message)
            channel_logger.info("<%s> %s", nick, clean_message)

        # Log private messages
        if is_pm:
            pm_logger = get_pm_logger(self.network_name, nick, self.config.paths)
            clean_message = strip_irc_formatting(message)
            pm_logger.info("<%s> %s", nick, clean_message)

        if channel and await self._moderate_message(nick, channel, message):
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
            tags=message_tags,
            account=account,
            server_time=server_time,
        )
        handled = await self.commands.dispatch(ctx)
        if not handled:
            await self.plugins.on_message(
                nick,
                channel or nick,
                message,
                hostmask=hostmask,
                tags=message_tags,
                account=account,
                server_time=server_time,
            )

    async def _handle_action(
        self,
        nick: str,
        target: str,
        action_text: str,
        prefix: str = "",
        tags: dict[str, str | None] | None = None,
        server_time: datetime | None = None,
        account: str | None = None,
    ) -> None:
        """Handle ACTION (\x01ACTION ...\x01).

        Args:
            nick: Sender nickname
            target: Message target (channel or bot nick)
            action_text: Action text (without \x01 markers)
            prefix: IRC prefix (nick!user@host)
        """
        channel = self._features.channel_from_target(target)
        is_pm = self._same_identifier(target, self._current_nick)

        # Log channel actions
        if channel and self._channel_logging_enabled(channel):
            channel_logger = get_channel_logger(
                self.network_name, channel, self.config.paths
            )
            clean_text = strip_irc_formatting(action_text)
            channel_logger.info("* %s %s", nick, clean_text)

        # Log PM actions
        if is_pm:
            pm_logger = get_pm_logger(self.network_name, nick, self.config.paths)
            clean_text = strip_irc_formatting(action_text)
            pm_logger.info("* %s %s", nick, clean_text)

        if channel and await self._moderate_message(nick, channel, action_text):
            return
        user = self.state.ensure_user(nick, prefix)
        if account is not None:
            user.account = account
        await self.plugins.on_action(
            nick,
            channel,
            action_text,
            prefix,
            user.account,
            dict(tags or {}),
            server_time,
        )

    async def _handle_notice(
        self,
        nick: str,
        target: str,
        message: str,
        prefix: str = "",
        tags: dict[str, str | None] | None = None,
        server_time: datetime | None = None,
        account: str | None = None,
    ) -> None:
        """Handle NOTICE messages (channel or PM).

        Args:
            nick: Sender nickname (or server name)
            target: Message target (channel or bot nick)
            message: Notice content
        """
        channel = self._features.channel_from_target(target)
        is_pm = self._same_identifier(target, self._current_nick)

        # Log channel notices
        if channel and self._channel_logging_enabled(channel):
            channel_logger = get_channel_logger(
                self.network_name, channel, self.config.paths
            )
            clean_message = strip_irc_formatting(message)
            channel_logger.info("--%s-- %s", nick, clean_message)

        # Log PM notices (NickServ, ChanServ, etc.)
        if is_pm:
            pm_logger = get_pm_logger(self.network_name, nick, self.config.paths)
            clean_message = strip_irc_formatting(message)
            pm_logger.info("--%s-- %s", nick, clean_message)

        user = self.state.ensure_user(nick, prefix)
        if account is not None:
            user.account = account
        await self.plugins.on_notice(
            nick,
            channel,
            message,
            prefix,
            user.account,
            dict(tags or {}),
            server_time,
        )

    async def _moderate_message(self, nick: str, channel: str, message: str) -> bool:
        if self._same_identifier(nick, self._current_nick):
            return False
        violation = await self.moderation.check_message(nick, channel, message)
        if not violation:
            return False
        action, reason = violation
        moderation_commands = await self.moderation.apply_action(
            action, nick, channel, reason
        )
        for moderation_command in moderation_commands:
            await self.send_raw(moderation_command)
        return True

    async def send_raw(
        self,
        message: str,
        *,
        sensitive: bool = False,
        priority: bool = False,
    ) -> None:
        if any(character in message for character in ("\r", "\n", "\0")):
            raise ValueError("IRC messages must not contain CR, LF, or NUL")
        encoded = message.encode("utf-8")
        if len(encoded) > 510:
            raise ValueError("IRC message exceeds the 510-byte protocol limit")
        if not self.writer:
            raise ConnectionError("IRC client is not connected")

        # Keepalive and registration traffic must not sit behind a flooded
        # application queue. The write lock still serializes it with a write
        # already in progress.
        if priority:
            await self._send_direct(message, sensitive=sensitive)
            return

        if self._send_queue is not None and self._sender_task is not None:
            result = asyncio.get_running_loop().create_future()
            self._send_sequence += 1
            item = (
                _SEND_PRIORITY if priority else _SEND_NORMAL,
                self._send_sequence,
                message,
                sensitive,
                result,
            )
            try:
                await asyncio.wait_for(self._send_queue.put(item), timeout=5.0)
            except TimeoutError as exc:
                raise ConnectionError("IRC send queue is full") from exc
            await result
            return

        await self._send_direct(message, sensitive=sensitive)

    async def _send_direct(self, message: str, *, sensitive: bool = False) -> None:
        writer = self.writer
        if writer is None:
            raise ConnectionError("IRC client is not connected")
        logged_message = "<redacted>" if sensitive else message
        self.logger.debug(">> %s", logged_message)

        # Raw IRC logging (only when DEBUG level)
        if self.logger.isEnabledFor(logging.DEBUG):
            raw_logger = get_raw_logger(self.network_name, self.config.paths)
            raw_logger.debug(">> %s", logged_message)

        async with self._write_lock:
            writer.write((message + "\r\n").encode())
            await writer.drain()

    async def _send_loop(self) -> None:
        assert self._send_queue is not None
        tokens = float(self.config.network.send_burst)
        last_refill = time.monotonic()
        try:
            while True:
                priority, _, message, sensitive, result = await self._send_queue.get()
                if result.cancelled():
                    self._send_queue.task_done()
                    continue
                try:
                    if priority != _SEND_PRIORITY:
                        now = time.monotonic()
                        tokens = min(
                            float(self.config.network.send_burst),
                            tokens
                            + (now - last_refill)
                            * self.config.network.send_rate_per_second,
                        )
                        last_refill = now
                        if tokens < 1.0:
                            delay = (
                                1.0 - tokens
                            ) / self.config.network.send_rate_per_second
                            await asyncio.sleep(delay)
                            last_refill = time.monotonic()
                            tokens = 0.0
                        else:
                            tokens -= 1.0
                    await self._send_direct(message, sensitive=sensitive)
                except Exception as exc:  # noqa: BLE001 - fail the connection boundary
                    if not result.done():
                        result.set_exception(exc)
                    if self.writer:
                        self.writer.close()
                    self._fail_send_queue(exc)
                    return
                else:
                    if not result.done():
                        result.set_result(None)
                finally:
                    self._send_queue.task_done()
        finally:
            self._fail_send_queue(ConnectionError("IRC sender stopped"))

    async def _dispatch_application(
        self, event: str, coroutine: Coroutine[object, object, None]
    ) -> None:
        """Queue application work without blocking the IRC protocol reader."""
        if self._event_queue is None or self._event_task is None:
            await coroutine
            return
        try:
            self._event_queue.put_nowait((event, coroutine))
        except asyncio.QueueFull:
            coroutine.close()
            self.logger.warning(
                "Dropping %s application event because the queue is full", event
            )

    async def _event_loop(self) -> None:
        assert self._event_queue is not None
        while True:
            event, coroutine = await self._event_queue.get()
            try:
                await coroutine
            except asyncio.CancelledError:
                current_task = asyncio.current_task()
                if current_task and current_task.cancelling():
                    raise
                self.logger.warning("Application event %s cancelled itself", event)
            except Exception:
                self.logger.exception("Application event %s failed", event)
            finally:
                self._event_queue.task_done()

    def _close_event_queue(self) -> None:
        if self._event_queue is None:
            return
        while True:
            try:
                _, coroutine = self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            coroutine.close()
            self._event_queue.task_done()

    def _fail_send_queue(self, error: Exception) -> None:
        if self._send_queue is None:
            return
        while True:
            try:
                _, _, _, _, result = self._send_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not result.done():
                result.set_exception(error)
            self._send_queue.task_done()

    async def send_privmsg(
        self, target: str, message: str, *, sensitive: bool = False
    ) -> None:
        if not target or any(
            character.isspace() or character in "\r\n\0:" for character in target
        ):
            raise ValueError(f"Invalid IRC target: {target!r}")
        clean_message = " ".join(message.replace("\0", "").splitlines()).strip()
        prefix = f"PRIVMSG {target} :"
        maximum = 510 - len(prefix.encode("utf-8"))
        clean_message = self._truncate_utf8(clean_message, maximum)
        await self.send_raw(prefix + clean_message, sensitive=sensitive)

    async def join_channels(self, channels: list[str]) -> None:
        for channel in channels:
            if (
                not channel
                or any(character.isspace() for character in channel)
                or any(character in channel for character in "\r\n\0,:")
            ):
                raise ValueError(f"Invalid IRC channel: {channel!r}")
            await self.send_raw(f"JOIN {channel}")

    async def _handle_cap(self, params: list[str], trailing: str) -> None:
        subcommand = params[1].upper() if len(params) > 1 else ""
        capability_text = trailing or " ".join(
            param for param in params[2:] if param != "*"
        )
        capability_tokens = capability_text.split()
        capabilities = {token.removeprefix("-") for token in capability_tokens}
        if subcommand == "LS":
            for capability in capability_tokens:
                name, _, values = capability.partition("=")
                self._offered_capabilities[name] = values or None
                if name == "sasl" and values:
                    self._sasl_mechanisms.update(
                        mechanism.upper() for mechanism in values.split(",")
                    )
            if params and params[-1] == "*":
                return
            mechanism = self.auth.sasl_mechanism()
            if self.config.auth.sasl_enabled:
                if "sasl" not in self._offered_capabilities:
                    await self._end_cap_negotiation()
                    raise ConnectionError("SASL was not advertised by the server")
                if self._sasl_mechanisms and mechanism not in self._sasl_mechanisms:
                    await self._end_cap_negotiation()
                    raise ConnectionError(f"Server does not support SASL {mechanism}")

            optional = []
            if self.config.network.ircv3_enabled:
                optional = [
                    capability
                    for capability in self.config.network.ircv3_capabilities
                    if capability in self._offered_capabilities and capability != "sasl"
                ]
            requests = (["sasl"] if self.config.auth.sasl_enabled else []) + optional
            self._pending_capabilities.update(requests)
            if self.config.auth.sasl_enabled:
                await self.send_raw("CAP REQ :sasl", priority=True)
            if optional:
                await self._request_capabilities(optional)
            if not requests:
                await self._end_cap_negotiation()
        elif subcommand == "ACK":
            for token in capability_tokens:
                disabled = token.startswith("-")
                capability = token[1:] if disabled else token
                self._pending_capabilities.discard(capability)
                if disabled:
                    self._active_capabilities.discard(capability)
                    if capability == "sasl" and self.config.auth.sasl_enabled:
                        await self._end_cap_negotiation()
                        raise ConnectionError(
                            "Server disabled the required SASL capability"
                        )
                else:
                    self._active_capabilities.add(capability)
            if "sasl" in capabilities and "sasl" in self._active_capabilities:
                mechanism = self.auth.sasl_mechanism()
                self._sasl_in_progress = True
                await self.send_raw(f"AUTHENTICATE {mechanism}", priority=True)
            else:
                await self._maybe_end_cap_negotiation()
        elif subcommand == "NAK":
            self._pending_capabilities.difference_update(capabilities)
            if "sasl" in capabilities:
                await self._end_cap_negotiation()
                raise ConnectionError("Server rejected the required SASL capability")
            self.logger.warning(
                "Server rejected optional capabilities: %s", capability_text
            )
            await self._maybe_end_cap_negotiation()
        elif subcommand == "NEW":
            for capability in capability_tokens:
                name, _, value = capability.partition("=")
                self._offered_capabilities[name] = value or None
            wanted = [
                capability
                for capability in self.config.network.ircv3_capabilities
                if capability in self._offered_capabilities
                and capability not in self._active_capabilities
                and capability not in self._pending_capabilities
            ]
            self._pending_capabilities.update(wanted)
            if wanted:
                await self._request_capabilities(wanted)
        elif subcommand == "DEL":
            for capability in capabilities:
                self._offered_capabilities.pop(capability, None)
                self._active_capabilities.discard(capability)
                self._pending_capabilities.discard(capability)

    async def _request_capabilities(self, capabilities: list[str]) -> None:
        chunk: list[str] = []
        for capability in capabilities:
            candidate = " ".join([*chunk, capability])
            if len(f"CAP REQ :{candidate}".encode()) > 510 and chunk:
                await self.send_raw(f"CAP REQ :{' '.join(chunk)}", priority=True)
                chunk = [capability]
            else:
                chunk.append(capability)
        if chunk:
            await self.send_raw(f"CAP REQ :{' '.join(chunk)}", priority=True)

    async def _end_cap_negotiation(self) -> None:
        if self._cap_end_sent:
            return
        self._cap_end_sent = True
        await self.send_raw("CAP END", priority=True)

    async def _maybe_end_cap_negotiation(self) -> None:
        sasl_done = not self.config.auth.sasl_enabled or self._sasl_complete
        if not self._pending_capabilities and not self._sasl_in_progress and sasl_done:
            await self._end_cap_negotiation()

    async def _handle_authenticate(self, params: list[str], trailing: str) -> None:
        challenge = trailing or (params[0] if params else "")
        if not self._sasl_in_progress or challenge != "+":
            return
        if self.auth.sasl_mechanism() == "EXTERNAL":
            await self.send_raw("AUTHENTICATE +", sensitive=True, priority=True)
            return
        payload = self.auth.sasl_plain_payload()
        if not payload:
            self.logger.error("SASL PLAIN is enabled but credentials are incomplete")
            await self.send_raw("AUTHENTICATE *", priority=True)
            return
        for offset in range(0, len(payload), 400):
            await self.send_raw(
                f"AUTHENTICATE {payload[offset : offset + 400]}",
                sensitive=True,
                priority=True,
            )
        if len(payload) % 400 == 0:
            await self.send_raw("AUTHENTICATE +", sensitive=True, priority=True)

    async def _after_welcome(self) -> None:
        if self._registration_complete:
            return
        self._registration_complete = True
        self._registration_event.set()
        credentials = self.auth.nickserv_credentials()
        if credentials:
            username, password = credentials
            await self.send_privmsg(
                self.config.auth.nickserv_service,
                f"IDENTIFY {username} {password}",
                sensitive=True,
            )
        if self.config.network.channels:
            await self.join_channels(self.config.network.channels)

    @staticmethod
    def _truncate_utf8(value: str, maximum: int) -> str:
        encoded = value.encode("utf-8")
        if len(encoded) <= maximum:
            return value
        return encoded[:maximum].decode("utf-8", errors="ignore")

    @staticmethod
    def _text_parameter(message: IRCMessage, index: int) -> str:
        """Read the final parameter with or without IRC's optional colon."""
        if message.trailing is not None:
            return message.trailing
        if len(message.params) > index:
            return message.params[index]
        return ""

    def _channel_logging_enabled(self, channel: str) -> bool:
        entries = self.config.logging.channel_logging
        for entry in entries:
            if self._same_identifier(entry.channel, channel):
                return entry.enabled
        return False

    def _same_identifier(self, left: str, right: str) -> bool:
        return self._features.casefold(left) == self._features.casefold(right)

    @staticmethod
    def _parse_message(line: str) -> tuple[str | None, str, list[str], str]:
        """Compatibility wrapper for older plugins using the private parser."""
        message: IRCMessage = parse_message(line)
        return (
            message.prefix,
            message.command,
            list(message.params),
            message.trailing or "",
        )
