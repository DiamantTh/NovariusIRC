"""Configurable, channel-aware IRC message moderation."""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

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

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.user_status: dict[str, dict[str, UserStatus]] = {}
        self.actions: list[ModerationAction] = []
        self.banned_users: set[tuple[str, str]] = set()
        self.muted_users: dict[tuple[str, str], datetime] = {}

    def _channel_config(self, channel: str) -> dict[str, Any]:
        overrides = self.config.get("channels", {})
        override = overrides.get(channel, overrides.get(channel.lower(), {}))
        global_config = {
            key: value for key, value in self.config.items() if key != "channels"
        }
        return _merge(global_config, override)

    def _status(self, nick: str, channel: str) -> UserStatus:
        channel_key = channel.lower()
        nick_key = nick.lower()
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

        key = (channel.lower(), nick.lower())
        now = _now()
        muted_until = self.muted_users.get(key)
        if muted_until:
            if muted_until > now:
                return "mute", "User is currently muted"
            self.muted_users.pop(key, None)
        if key in self.banned_users:
            return "ban", "User is banned"

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
                ), f"Rate limit exceeded ({maximum} msgs/min)"

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
                ), "Repeated-message spam detected"

        badwords = config.get("badwords", {})
        if badwords.get("enabled", False):
            for expression in badwords.get("list", []):
                try:
                    if re.search(expression, message, flags=re.IGNORECASE):
                        return self._configured_action(badwords), "Badword detected"
                except re.error as exc:
                    logger.warning("Invalid badword regex %r: %s", expression, exc)

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
                ), f"Excessive caps ({percentage:.0f}%)"

        return None

    async def apply_action(
        self,
        action: str,
        nick: str,
        channel: str,
        reason: str,
        duration: int | None = None,
    ) -> list[str]:
        action = action.lower()
        if action not in VALID_ACTIONS:
            logger.warning("Refusing unknown moderation action %r", action)
            return []

        status = self._status(nick, channel)
        config = self._channel_config(channel)
        key = (channel.lower(), nick.lower())

        if action == "warn":
            status.warnings += 1
            warnings = config.get("warnings", {})
            if warnings.get("enabled", True):
                if status.warnings >= int(warnings.get("to_ban", 5)):
                    action = "ban"
                    reason = f"Accumulated {status.warnings} warnings"
                elif status.warnings >= int(warnings.get("to_kick", 3)):
                    action = "kick"
                    reason = f"Accumulated {status.warnings} warnings"

        self.actions.append(
            ModerationAction(
                action=action,
                user=nick,
                channel=channel,
                reason=reason,
                duration=duration,
            )
        )
        logger.info("[%s] Applying %s to %s: %s", channel, action, nick, reason)

        if action == "warn":
            return [f"NOTICE {nick} :{reason} (Warning {status.warnings})"]
        if action == "mute":
            spam_duration = int(config.get("spam", {}).get("duration_seconds", 300))
            mute_duration = duration if duration is not None else spam_duration
            self.muted_users[key] = _now() + timedelta(seconds=max(1, mute_duration))
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
        return self._status(nick, channel).warnings

    def reset_warnings(self, nick: str, channel: str) -> None:
        self._status(nick, channel).warnings = 0

    async def unban_user(self, nick: str, channel: str | None = None) -> None:
        nick_key = nick.lower()
        self.banned_users = {
            key
            for key in self.banned_users
            if not (
                key[1] == nick_key and (channel is None or key[0] == channel.lower())
            )
        }

    async def unmute_user(self, nick: str, channel: str | None = None) -> None:
        nick_key = nick.lower()
        self.muted_users = {
            key: expiry
            for key, expiry in self.muted_users.items()
            if not (
                key[1] == nick_key and (channel is None or key[0] == channel.lower())
            )
        }

    def rename_user(self, old_nick: str, new_nick: str) -> None:
        old_key = old_nick.lower()
        new_key = new_nick.lower()
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
