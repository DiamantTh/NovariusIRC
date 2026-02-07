"""Moderation system for NovariusIRC.

Provides configurable moderation features:
- Rate limiting (messages per minute)
- Spam detection (repeated messages)
- Badword filtering
- User bans/mutes
- Action logging
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

from novariusirc.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ModerationAction:
    """Record of a moderation action."""

    action: str  # "warn", "mute", "kick", "ban"
    user: str
    channel: str
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)
    moderator: str = "system"
    duration: Optional[int] = None  # seconds, None = permanent


@dataclass
class UserStatus:
    """Status of a user in a channel."""

    nick: str
    channel: str
    warnings: int = 0
    muted_until: Optional[datetime] = None
    banned: bool = False
    last_message_time: datetime = field(default_factory=datetime.now)
    message_count_minute: int = 0


class ModerationConfig:
    """Moderation configuration from TOML."""

    def __init__(self, config_dict: Optional[Dict] = None):
        """Initialize moderation config.

        Args:
            config_dict: Configuration dict (e.g., from moderation.toml)
        """
        if config_dict is None:
            config_dict = {}

        # Global settings
        self.enabled = config_dict.get("enabled", True)
        self.log_file = Path(config_dict.get("log_file", "logs/moderation.log"))

        # Rate limiting
        self.rate_limit = config_dict.get("rate_limit", {})
        self.rate_limit_enabled = self.rate_limit.get("enabled", False)
        self.rate_limit_messages = self.rate_limit.get("messages_per_minute", 5)
        self.rate_limit_action = self.rate_limit.get("action", "warn")  # warn, mute, kick

        # Spam detection
        self.spam = config_dict.get("spam", {})
        self.spam_enabled = self.spam.get("enabled", False)
        self.spam_threshold = self.spam.get("threshold", 3)  # consecutive same messages
        self.spam_action = self.spam.get("action", "mute")
        self.spam_duration = self.spam.get("duration_seconds", 300)  # 5 min mute

        # Caps lock
        self.caps = config_dict.get("caps", {})
        self.caps_enabled = self.caps.get("enabled", False)
        self.caps_threshold = self.caps.get("threshold_percent", 80)
        self.caps_action = self.caps.get("action", "warn")

        # Badwords
        self.badwords = config_dict.get("badwords", {})
        self.badwords_enabled = self.badwords.get("enabled", False)
        self.badwords_list = self.badwords.get("list", [])
        self.badwords_action = self.badwords.get("action", "warn")

        # Warnings
        self.warnings = config_dict.get("warnings", {})
        self.warnings_enabled = self.warnings.get("enabled", True)
        self.warnings_to_kick = self.warnings.get("to_kick", 3)
        self.warnings_to_ban = self.warnings.get("to_ban", 5)

        # Channel-specific overrides
        self.channel_overrides: Dict[str, Dict] = config_dict.get("channels", {})


class ModerationManager:
    """Manages moderation for IRC bot."""

    def __init__(self, config: Optional[ModerationConfig | Dict] = None):
        """Initialize moderation manager.

        Args:
            config: ModerationConfig instance
        """
        if isinstance(config, dict):
            self.config = ModerationConfig(config)
        else:
            self.config = config or ModerationConfig()
        self.user_status: Dict[str, Dict[str, UserStatus]] = {}  # channel -> nick -> status
        self.actions: List[ModerationAction] = []
        self.banned_users: Set[str] = set()
        self.muted_users: Dict[str, datetime] = {}  # user -> unmute_time

        # Compile badword regexes
        self.badword_patterns: List[re.Pattern] = []
        for word in self.config.badwords_list:
            try:
                pattern = re.compile(word, re.IGNORECASE)
                self.badword_patterns.append(pattern)
            except re.error as e:
                logger.warning(f"Invalid badword regex '{word}': {e}")

    async def check_message(
        self, nick: str, channel: str, message: str
    ) -> Optional[tuple[str, str]]:
        """Check message for moderation violations.

        Args:
            nick: User nick
            channel: Channel name
            message: Message text

        Returns:
            Tuple of (action, reason) if violation found, else None
        """
        # Get config for this channel (with overrides)
        channel_config = self._get_channel_config(channel)

        if not channel_config.enabled:
            return None

        # Check if user is muted
        if nick in self.muted_users:
            if self.muted_users[nick] > datetime.now():
                return ("mute", "User is currently muted")
            else:
                del self.muted_users[nick]

        # Check if user is banned
        if nick in self.banned_users:
            return ("ban", "User is banned")

        # Initialize user status
        if channel not in self.user_status:
            self.user_status[channel] = {}
        if nick not in self.user_status[channel]:
            self.user_status[channel][nick] = UserStatus(nick=nick, channel=channel)

        status = self.user_status[channel][nick]

        # Rate limiting
        if channel_config.rate_limit_enabled:
            result = self._check_rate_limit(status, channel_config)
            if result:
                return result

        # Badword filter
        if channel_config.badwords_enabled:
            result = self._check_badwords(message, channel_config)
            if result:
                status.warnings += 1
                return result

        # Caps lock detection
        if channel_config.caps_enabled:
            result = self._check_caps(message, channel_config)
            if result:
                status.warnings += 1
                return result

        # Update status
        status.last_message_time = datetime.now()
        status.message_count_minute = 0  # Reset by rate limit checker

        return None

    def _check_rate_limit(
        self, status: UserStatus, config: "ModerationConfig"
    ) -> Optional[tuple[str, str]]:
        """Check if user exceeds message rate limit."""
        max_msgs = config.rate_limit_messages
        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)

        if status.last_message_time > minute_ago:
            status.message_count_minute += 1
            if status.message_count_minute > max_msgs:
                return (config.rate_limit_action, f"Rate limit exceeded ({max_msgs} msgs/min)")

        else:
            status.message_count_minute = 1

        return None

    def _check_badwords(self, message: str, config: "ModerationConfig") -> Optional[tuple[str, str]]:
        """Check message for badwords."""
        for pattern in config.badword_patterns:
            if pattern.search(message):
                return (config.badwords_action, "Badword detected")

        return None

    def _check_caps(self, message: str, config: "ModerationConfig") -> Optional[tuple[str, str]]:
        """Check for excessive caps lock."""
        if len(message) < 5:
            return None  # Ignore short messages

        caps_count = sum(1 for c in message if c.isupper())
        caps_percent = (caps_count / len(message)) * 100

        if caps_percent >= config.caps_threshold:
            return (config.caps_action, f"Excessive caps ({caps_percent:.0f}%)")

        return None

    async def apply_action(
        self, action: str, nick: str, channel: str, reason: str, duration: Optional[int] = None
    ) -> str:
        """Apply moderation action to user.

        Args:
            action: Action type ("warn", "mute", "kick", "ban")
            nick: User nick
            channel: Channel name
            reason: Reason for action
            duration: Duration in seconds (for mute)

        Returns:
            IRC command to execute
        """
        logger.info(f"[{channel}] Applying {action} to {nick}: {reason}")

        # Record action
        mod_action = ModerationAction(
            action=action, user=nick, channel=channel, reason=reason, duration=duration
        )
        self.actions.append(mod_action)

        # Initialize user status if needed
        if channel not in self.user_status:
            self.user_status[channel] = {}
        if nick not in self.user_status[channel]:
            self.user_status[channel][nick] = UserStatus(nick=nick, channel=channel)

        status = self.user_status[channel][nick]

        if action == "warn":
            status.warnings += 1
            channel_config = self._get_channel_config(channel)
            warnings_to_kick = channel_config.get("warnings_to_kick", self.config.warnings_to_kick)
            warnings_to_ban = channel_config.get("warnings_to_ban", self.config.warnings_to_ban)

            if status.warnings >= warnings_to_ban:
                return await self.apply_action("ban", nick, channel, f"Accumulated {status.warnings} warnings")
            elif status.warnings >= warnings_to_kick:
                return await self.apply_action("kick", nick, channel, f"Accumulated {status.warnings} warnings")

            return f"NOTICE {nick} :{reason} (Warning {status.warnings})"

        elif action == "mute":
            mute_duration = duration or 300
            self.muted_users[nick] = datetime.now() + timedelta(seconds=mute_duration)
            return f"MODE {channel} +q {nick}!*@*"  # Quiet mode

        elif action == "kick":
            status.warnings = 0
            return f"KICK {channel} {nick} :{reason}"

        elif action == "ban":
            self.banned_users.add(nick)
            status.banned = True
            return f"KICK {channel} {nick} :{reason}"

        return ""

    def _get_channel_config(self, channel: str) -> "ModerationConfig":
        """Get moderation config for specific channel.

        Returns a ModerationConfig merged with channel-specific overrides.

        Args:
            channel: Channel name

        Returns:
            ModerationConfig with channel overrides applied
        """
        # Start with global config
        channel_dict = self.config.channel_overrides.get(channel)

        if not channel_dict:
            # No overrides, use global
            return self.config

        # Create merged config with overrides
        merged = ModerationConfig()

        # Copy global settings
        merged.enabled = channel_dict.get("enabled", self.config.enabled)
        merged.log_file = Path(channel_dict.get("log_file", str(self.config.log_file)))

        # Merge rate limit
        if "rate_limit" in channel_dict:
            override = channel_dict["rate_limit"]
            merged.rate_limit_enabled = override.get("enabled", self.config.rate_limit_enabled)
            merged.rate_limit_messages = override.get(
                "messages_per_minute", self.config.rate_limit_messages
            )
            merged.rate_limit_action = override.get("action", self.config.rate_limit_action)

        # Merge spam
        if "spam" in channel_dict:
            override = channel_dict["spam"]
            merged.spam_enabled = override.get("enabled", self.config.spam_enabled)
            merged.spam_threshold = override.get("threshold", self.config.spam_threshold)
            merged.spam_action = override.get("action", self.config.spam_action)
            merged.spam_duration = override.get("duration_seconds", self.config.spam_duration)

        # Merge caps
        if "caps" in channel_dict:
            override = channel_dict["caps"]
            merged.caps_enabled = override.get("enabled", self.config.caps_enabled)
            merged.caps_threshold = override.get("threshold_percent", self.config.caps_threshold)
            merged.caps_action = override.get("action", self.config.caps_action)

        # Merge badwords
        if "badwords" in channel_dict:
            override = channel_dict["badwords"]
            merged.badwords_enabled = override.get("enabled", self.config.badwords_enabled)
            merged.badwords_list = override.get("list", self.config.badwords_list)
            merged.badwords_action = override.get("action", self.config.badwords_action)

            # Recompile badword patterns if overridden
            merged.badword_patterns = []
            for word in merged.badwords_list:
                try:
                    pattern = re.compile(word, re.IGNORECASE)
                    merged.badword_patterns.append(pattern)
                except re.error as e:
                    logger.warning(f"Invalid badword regex '{word}' in {channel}: {e}")

        # Merge warnings
        if "warnings" in channel_dict:
            override = channel_dict["warnings"]
            merged.warnings_enabled = override.get("enabled", self.config.warnings_enabled)
            merged.warnings_to_kick = override.get("to_kick", self.config.warnings_to_kick)
            merged.warnings_to_ban = override.get("to_ban", self.config.warnings_to_ban)

        return merged

    def get_user_warnings(self, nick: str, channel: str) -> int:
        """Get warning count for user in channel."""
        if channel in self.user_status and nick in self.user_status[channel]:
            return self.user_status[channel][nick].warnings
        return 0

    def reset_warnings(self, nick: str, channel: str) -> None:
        """Reset warnings for user."""
        if channel in self.user_status and nick in self.user_status[channel]:
            self.user_status[channel][nick].warnings = 0

    async def unban_user(self, nick: str) -> None:
        """Unban a user."""
        if nick in self.banned_users:
            self.banned_users.discard(nick)
            logger.info(f"Unbanned user: {nick}")

    async def unmute_user(self, nick: str) -> None:
        """Unmute a user."""
        if nick in self.muted_users:
            del self.muted_users[nick]
            logger.info(f"Unmuted user: {nick}")
