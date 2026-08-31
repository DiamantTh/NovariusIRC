"""Connection-local IRC users, channels, and membership state."""

from __future__ import annotations

from dataclasses import dataclass, field

from .protocol import IRCFeatures


def split_source(source: str) -> tuple[str, str | None, str | None]:
    """Split a user source into nick, username, and hostname."""
    nick, bang, remainder = source.partition("!")
    if not bang:
        return nick, None, None
    username, at, hostname = remainder.partition("@")
    return nick, username or None, hostname if at and hostname else None


def normalize_account(account: str | None) -> str | None:
    """Turn IRC's logged-out account marker into ``None``."""
    return None if not account or account == "*" else account


@dataclass
class IRCUser:
    nick: str
    username: str | None = None
    hostname: str | None = None
    account: str | None = None
    realname: str | None = None
    away: str | None = None
    is_away: bool | None = None

    @property
    def hostmask(self) -> str:
        if self.username is not None and self.hostname is not None:
            return f"{self.nick}!{self.username}@{self.hostname}"
        return self.nick


@dataclass
class IRCMembership:
    user: IRCUser
    modes: set[str] = field(default_factory=set)

    @property
    def nick(self) -> str:
        return self.user.nick


@dataclass
class IRCChannel:
    name: str
    members: dict[str, IRCMembership] = field(default_factory=dict)
    names_complete: bool = False
    names_in_progress: bool = False
    names_seen: set[str] = field(default_factory=set)
    names_removed: set[str] = field(default_factory=set)
    topic: str | None = None
    topic_setter: str | None = None
    topic_set_at: int | None = None
    created_at: int | None = None
    list_modes: dict[str, set[str]] = field(default_factory=dict)
    parameter_modes: dict[str, str] = field(default_factory=dict)
    flag_modes: set[str] = field(default_factory=set)


class IRCState:
    """Maintain state using the active server CASEMAPPING and PREFIX values."""

    def __init__(self, features: IRCFeatures):
        self.features = features
        self.users: dict[str, IRCUser] = {}
        self.channels: dict[str, IRCChannel] = {}

    def clear(self) -> None:
        self.users.clear()
        self.channels.clear()

    def prune_membership_modes(self) -> None:
        """Drop membership modes no longer present in the active PREFIX token."""
        valid_modes = set(self.features.prefix_modes)
        for channel in self.channels.values():
            for membership in channel.members.values():
                membership.modes.intersection_update(valid_modes)

    def clear_channel_modes(self) -> None:
        """Discard mode state after the server changes CHANMODES semantics."""
        for channel in self.channels.values():
            channel.list_modes.clear()
            channel.parameter_modes.clear()
            channel.flag_modes.clear()

    def reindex(self) -> None:
        """Rebuild identifier keys after a CASEMAPPING change."""
        self.users = {
            self.features.casefold(user.nick): user for user in self.users.values()
        }
        rebuilt_channels: dict[str, IRCChannel] = {}
        for channel in self.channels.values():
            seen_memberships = [
                membership
                for key, membership in channel.members.items()
                if key in channel.names_seen
            ]
            channel.members = {
                self.features.casefold(membership.nick): membership
                for membership in channel.members.values()
            }
            channel.names_seen = {
                self.features.casefold(membership.nick)
                for membership in seen_memberships
            }
            channel.names_removed = {
                self.features.casefold(key) for key in channel.names_removed
            }
            rebuilt_channels[self.features.casefold(channel.name)] = channel
        self.channels = rebuilt_channels

    def get_user(self, nick: str) -> IRCUser | None:
        return self.users.get(self.features.casefold(nick))

    def get_channel(self, name: str) -> IRCChannel | None:
        return self.channels.get(self.features.casefold(name))

    def ensure_user(self, nick: str, source: str = "") -> IRCUser:
        key = self.features.casefold(nick)
        user = self.users.get(key)
        if user is None:
            user = IRCUser(nick=nick)
            self.users[key] = user
        else:
            user.nick = nick
        if source:
            source_nick, username, hostname = split_source(source)
            if self.features.casefold(source_nick) == key:
                user.username = username or user.username
                user.hostname = hostname or user.hostname
        return user

    def ensure_channel(self, name: str) -> IRCChannel:
        key = self.features.casefold(name)
        channel = self.channels.get(key)
        if channel is None:
            channel = IRCChannel(name=name)
            self.channels[key] = channel
        return channel

    def join(
        self,
        source: str,
        channel_name: str,
        *,
        account: str | None = None,
        realname: str | None = None,
    ) -> IRCMembership:
        nick, _, _ = split_source(source)
        user = self.ensure_user(nick, source)
        if account is not None:
            user.account = normalize_account(account)
        if realname is not None:
            user.realname = realname
        channel = self.ensure_channel(channel_name)
        key = self.features.casefold(nick)
        membership = channel.members.get(key)
        if membership is None:
            membership = IRCMembership(user=user)
            channel.members[key] = membership
        if channel.names_in_progress:
            channel.names_removed.discard(key)
            channel.names_seen.add(key)
        return membership

    def add_names(self, channel_name: str, names: str) -> None:
        channel = self.ensure_channel(channel_name)
        if not channel.names_in_progress:
            channel.names_in_progress = True
            channel.names_complete = False
            channel.names_seen.clear()
            channel.names_removed.clear()
        for entry in names.split():
            modes: set[str] = set()
            while entry and entry[0] in self.features.prefix_symbols:
                mode = self.features.mode_for_prefix(entry[0])
                if mode:
                    modes.add(mode)
                entry = entry[1:]
            if not entry:
                continue
            source = entry
            nick, _, _ = split_source(source)
            user = self.ensure_user(nick, source)
            key = self.features.casefold(nick)
            if key in channel.names_removed:
                continue
            channel.members[key] = IRCMembership(
                user=user,
                modes=modes,
            )
            channel.names_seen.add(key)

    def finish_names(self, channel_name: str) -> None:
        channel = self.ensure_channel(channel_name)
        if channel.names_in_progress:
            stale_keys = set(channel.members) - channel.names_seen
            stale_nicks = [channel.members[key].nick for key in stale_keys]
            for key in stale_keys:
                channel.members.pop(key, None)
            channel.names_seen.clear()
            channel.names_removed.clear()
            channel.names_in_progress = False
            for nick in stale_nicks:
                self._drop_orphan_user(nick)
        channel.names_complete = True

    def part(self, nick: str, channel_name: str) -> None:
        channel = self.get_channel(channel_name)
        if channel:
            key = self.features.casefold(nick)
            channel.members.pop(key, None)
            if channel.names_in_progress:
                channel.names_seen.discard(key)
                channel.names_removed.add(key)
            self._drop_orphan_user(nick)

    def remove_channel(self, channel_name: str) -> None:
        channel = self.channels.pop(self.features.casefold(channel_name), None)
        if channel:
            for membership in channel.members.values():
                self._drop_orphan_user(membership.nick)

    def quit(self, nick: str) -> list[str]:
        key = self.features.casefold(nick)
        channel_names: list[str] = []
        for channel in self.channels.values():
            if key in channel.members:
                channel_names.append(channel.name)
                channel.members.pop(key, None)
                if channel.names_in_progress:
                    channel.names_seen.discard(key)
                    channel.names_removed.add(key)
        self.users.pop(key, None)
        return channel_names

    def rename(self, old_nick: str, new_nick: str, source: str = "") -> IRCUser:
        old_key = self.features.casefold(old_nick)
        new_key = self.features.casefold(new_nick)
        user = self.users.pop(old_key, None) or self.ensure_user(old_nick, source)
        user.nick = new_nick
        self.users[new_key] = user
        for channel in self.channels.values():
            membership = channel.members.pop(old_key, None)
            if membership:
                channel.members[new_key] = membership
                if channel.names_in_progress:
                    channel.names_removed.add(old_key)
                    channel.names_seen.discard(old_key)
                    channel.names_seen.add(new_key)
        return user

    def set_account(self, source: str, account: str | None) -> IRCUser:
        nick, _, _ = split_source(source)
        user = self.ensure_user(nick, source)
        user.account = normalize_account(account)
        return user

    def set_away(self, source: str, message: str | None) -> IRCUser:
        nick, _, _ = split_source(source)
        user = self.ensure_user(nick, source)
        user.away = message
        user.is_away = message is not None
        return user

    def set_away_status(self, nick: str, is_away: bool) -> IRCUser:
        """Update away presence when WHO provides no away message."""
        user = self.ensure_user(nick)
        user.is_away = is_away
        if not is_away:
            user.away = None
        return user

    def change_host(self, source: str, username: str, hostname: str) -> IRCUser:
        nick, _, _ = split_source(source)
        user = self.ensure_user(nick, source)
        user.username = username
        user.hostname = hostname
        return user

    def set_membership_mode(
        self, channel_name: str, nick: str, mode: str, enabled: bool
    ) -> None:
        channel = self.get_channel(channel_name)
        if channel is None:
            return
        membership = channel.members.get(self.features.casefold(nick))
        if membership is None:
            return
        if enabled:
            membership.modes.add(mode)
        else:
            membership.modes.discard(mode)

    def channels_for(self, nick: str) -> list[str]:
        key = self.features.casefold(nick)
        return [
            channel.name for channel in self.channels.values() if key in channel.members
        ]

    def _drop_orphan_user(self, nick: str) -> None:
        key = self.features.casefold(nick)
        if not any(key in channel.members for channel in self.channels.values()):
            self.users.pop(key, None)
