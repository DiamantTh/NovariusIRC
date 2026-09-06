"""Configurable, channel-aware IRC message moderation."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from novariusirc.irc.protocol import irc_casefold

from .i18n import translate
from .moderation_store import ModerationStore, ServerModerationStore
from .rules import RegexRules, extract_urls

logger = logging.getLogger(__name__)

VALID_ACTIONS = {"warn", "mute", "kick", "ban"}


def _now() -> datetime:
    return datetime.now(UTC)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass
class ModerationAction:
    action: str
    user: str
    channel: str
    reason: str
    timestamp: datetime = field(default_factory=_now)
    moderator: str = "system"
    duration: int | None = None
    id: int | None = None


@dataclass
class UserStatus:
    nick: str
    channel: str
    warnings: int = 0
    banned: bool = False
    message_times: deque[datetime] = field(default_factory=deque)
    recent_messages: deque[str] = field(default_factory=deque)


class ModerationManager:
    """Evaluate messages and turn configured actions into IRC commands."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        casefold: Callable[[str], str] = irc_casefold,
        storage_path: str | None = None,
        storage_dsn: str | None = None,
        language: str = "en",
    ):
        self.config = config or {}
        self.casefold = casefold
        self.language = language
        self.user_status: dict[str, dict[str, UserStatus]] = {}
        self.actions: list[ModerationAction] = []
        self.banned_users: set[tuple[str, str]] = set()
        self.muted_users: dict[tuple[str, str], datetime] = {}
        self._rule_sets: dict[tuple[str, tuple[str, ...], tuple[str, ...]], RegexRules] = {}
        self.store = (
            ServerModerationStore(storage_dsn) if storage_dsn else
            ModerationStore(storage_path) if storage_path else None
        )
        self._restore_active_actions()

    def _restore_active_actions(self) -> None:
        if not self.store:
            return
        for action in self.store.active_actions():
            key = (self.casefold(action["channel"]), self.casefold(action["nick"]))
            if action["action"] == "ban":
                self.banned_users.add(key)
            else:
                created = action["created_at"]
                if isinstance(created, str):
                    created = datetime.fromisoformat(created)
                self.muted_users[key] = created + timedelta(seconds=action["duration_seconds"])

    def set_casefold(self, casefold: Callable[[str], str]) -> None:
        """Set the active network's identifier folding function."""
        if self.user_status or self.banned_users or self.muted_users:
            logger.info("Clearing transient moderation state after CASEMAPPING change")
            self.user_status.clear()
            self.banned_users.clear()
            self.muted_users.clear()
            self._restore_active_actions()
        self.casefold = casefold

    def _channel_config(self, channel: str) -> dict[str, Any]:
        overrides = self.config.get("channels", {})
        override = overrides.get(channel)
        if override is None:
            channel_key = self.casefold(channel)
            override = next(
                (
                    value
                    for configured_channel, value in overrides.items()
                    if self.casefold(configured_channel) == channel_key
                ),
                {},
            )
        global_config = {
            key: value for key, value in self.config.items() if key != "channels"
        }
        return _merge(global_config, override)

    def _tr(self, message: str, **values: object) -> str:
        return translate(message, self.language, **values)

    def _rules(self, name: str, section: dict[str, Any], allow: bool = False) -> RegexRules:
        patterns = tuple(str(value) for value in section.get("allowlist" if allow else "list", []))
        files = tuple(str(value) for value in section.get("allowlist_files" if allow else "files", []))
        key = (name, patterns, files)
        if key not in self._rule_sets:
            self._rule_sets[key] = RegexRules(patterns, files, logger)
        return self._rule_sets[key]

    def _status(self, nick: str, channel: str) -> UserStatus:
        channel_key = self.casefold(channel)
        nick_key = self.casefold(nick)
        statuses = self.user_status.setdefault(channel_key, {})
        return statuses.setdefault(nick_key, UserStatus(nick=nick, channel=channel))

    @staticmethod
    def _configured_action(section: dict[str, Any], default: str = "warn") -> str:
        action = str(section.get("action", default)).lower()
        if action not in VALID_ACTIONS:
            logger.warning("Ignoring invalid moderation action %r; using warn", action)
            return "warn"
        return action

    async def check_message(
        self, nick: str, channel: str, message: str
    ) -> tuple[str, str] | None:
        config = self._channel_config(channel)
        if not config.get("enabled", True):
            return None

        key = (self.casefold(channel), self.casefold(nick))
        now = _now()
        muted_until = self.muted_users.get(key)
        if muted_until:
            if muted_until > now:
                return "mute", self._tr("User is currently muted")
            self.muted_users.pop(key, None)
        if key in self.banned_users:
            return "ban", self._tr("User is banned")

        status = self._status(nick, channel)

        rate = config.get("rate_limit", {})
        if rate.get("enabled", False):
            cutoff = now - timedelta(minutes=1)
            while status.message_times and status.message_times[0] <= cutoff:
                status.message_times.popleft()
            status.message_times.append(now)
            maximum = max(1, int(rate.get("messages_per_minute", 5)))
            if len(status.message_times) > maximum:
                return self._configured_action(
                    rate
                ), self._tr("Rate limit exceeded ({maximum} msgs/min)", maximum=maximum)

        spam = config.get("spam", {})
        if spam.get("enabled", False):
            threshold = max(2, int(spam.get("threshold", 3)))
            status.recent_messages.append(message)
            while len(status.recent_messages) > threshold:
                status.recent_messages.popleft()
            if (
                len(status.recent_messages) == threshold
                and len(set(status.recent_messages)) == 1
            ):
                return self._configured_action(
                    spam, "mute"
                ), self._tr("Repeated-message spam detected")

        badwords = config.get("badwords", {})
        if badwords.get("enabled", False):
            bad_rules = self._rules("badwords", badwords)
            allowed_rules = self._rules("badwords", badwords, allow=True)
            if bad_rules.matches(message) and not allowed_rules.matches(message):
                return self._configured_action(badwords), self._tr("Badword detected")

        urls = config.get("urls", {})
        if urls.get("enabled", False):
            for url, hostname in extract_urls(message):
                allowed = self._rules("urls", urls, allow=True).matches(url, hostname)
                if urls.get("policy", "denylist") == "allowlist":
                    if not allowed:
                        return self._configured_action(urls), self._tr("URL is not allowed")
                elif self._rules("urls", urls).matches(url, hostname) and not allowed:
                    return self._configured_action(urls), self._tr("Blocked URL detected")

        caps = config.get("caps", {})
        letters = [character for character in message if character.isalpha()]
        if caps.get("enabled", False) and len(letters) >= 5:
            percentage = (
                sum(character.isupper() for character in letters) / len(letters) * 100
            )
            threshold = int(caps.get("threshold_percent", 80))
            if percentage >= threshold:
                return self._configured_action(
                    caps
                ), self._tr("Excessive caps ({percentage:.0f}%)", percentage=percentage)

        return None

    async def apply_action(
        self,
        action: str,
        nick: str,
        channel: str,
        reason: str,
        duration: int | None = None,
        account: str | None = None,
        hostmask: str | None = None,
    ) -> list[str]:
        action = action.lower()
        if action not in VALID_ACTIONS:
            logger.warning("Refusing unknown moderation action %r", action)
            return []

        status = self._status(nick, channel)
        config = self._channel_config(channel)
        key = (self.casefold(channel), self.casefold(nick))

        if action == "warn":
            if self.store:
                status.warnings = self.store.warning_count(nick, channel)
            status.warnings += 1
            warnings = config.get("warnings", {})
            if warnings.get("enabled", True):
                if status.warnings >= int(warnings.get("to_ban", 5)):
                    action = "ban"
                    reason = self._tr("Accumulated {count} warnings", count=status.warnings)
                elif status.warnings >= int(warnings.get("to_kick", 3)):
                    action = "kick"
                    reason = self._tr("Accumulated {count} warnings", count=status.warnings)

        if action == "mute" and duration is None:
            duration = int(config.get("spam", {}).get("duration_seconds", 300))

        recorded = ModerationAction(
                action=action,
                user=nick,
                channel=channel,
                reason=reason,
                duration=duration,
            )
        self.actions.append(recorded)
        if self.store:
            recorded.id = self.store.record_action(
                action=action, nick=nick, account=account, hostmask=hostmask,
                channel=channel, reason=reason, moderator=recorded.moderator,
                duration=duration, created_at=recorded.timestamp,
            )
        logger.info("[%s] Applying %s to %s: %s", channel, action, nick, reason)

        if action == "warn":
            warning = self._tr("Warning {count}", count=status.warnings)
            return [f"NOTICE {nick} :{reason} ({warning})"]
        if action == "mute":
            self.muted_users[key] = _now() + timedelta(seconds=max(1, duration or 1))
            return [f"MODE {channel} +q {nick}!*@*"]
        if action == "kick":
            return [f"KICK {channel} {nick} :{reason}"]

        self.banned_users.add(key)
        status.banned = True
        return [
            f"MODE {channel} +b {nick}!*@*",
            f"KICK {channel} {nick} :{reason}",
        ]

    def get_user_warnings(self, nick: str, channel: str) -> int:
        transient = self._status(nick, channel).warnings
        return self.store.warning_count(nick, channel) if self.store else transient

    def reset_warnings(self, nick: str, channel: str) -> None:
        self._status(nick, channel).warnings = 0
        if self.store:
            self.store.revoke(nick, channel, "warn")

    def add_evidence(
        self, action_id: int, *, kind: str, path: str, sha256: str | None = None,
        mime_type: str | None = None, size_bytes: int | None = None, note: str | None = None,
    ) -> int:
        if not self.store:
            raise RuntimeError("moderation storage is not configured")
        return self.store.add_evidence(
            action_id, kind=kind, path=path, sha256=sha256, mime_type=mime_type,
            size_bytes=size_bytes, note=note,
        )

    async def unban_user(self, nick: str, channel: str | None = None) -> None:
        nick_key = self.casefold(nick)
        self.banned_users = {
            key
            for key in self.banned_users
            if not (
                key[1] == nick_key
                and (channel is None or key[0] == self.casefold(channel))
            )
        }
        if self.store:
            self.store.revoke(nick, channel, "ban")

    async def unmute_user(self, nick: str, channel: str | None = None) -> None:
        nick_key = self.casefold(nick)
        self.muted_users = {
            key: expiry
            for key, expiry in self.muted_users.items()
            if not (
                key[1] == nick_key
                and (channel is None or key[0] == self.casefold(channel))
            )
        }
        if self.store:
            self.store.revoke(nick, channel, "mute")

    def rename_user(self, old_nick: str, new_nick: str) -> None:
        old_key = self.casefold(old_nick)
        new_key = self.casefold(new_nick)
        for channel, statuses in self.user_status.items():
            status = statuses.pop(old_key, None)
            if status:
                status.nick = new_nick
                statuses[new_key] = status
            old_pair = (channel, old_key)
            new_pair = (channel, new_key)
            if old_pair in self.banned_users:
                self.banned_users.remove(old_pair)
                self.banned_users.add(new_pair)
            if old_pair in self.muted_users:
                self.muted_users[new_pair] = self.muted_users.pop(old_pair)
