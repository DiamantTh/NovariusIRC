"""Configuration loading and validation."""

from __future__ import annotations

import builtins
import os
import re
import tomllib
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

DEFAULT_INCLUDE_FILES = ["secrets.toml"]

ENV_BOT_PREFIX = "NOVARIUSIRC_PREFIX"
ENV_BOT_LANGUAGE = "NOVARIUSIRC_LANG"

ENV_NETWORK_SERVER = "NOVARIUSIRC_SERVER"
ENV_NETWORK_PORT = "NOVARIUSIRC_PORT"
ENV_NETWORK_TLS = "NOVARIUSIRC_TLS"
ENV_NETWORK_NICK = "NOVARIUSIRC_NICK"
ENV_NETWORK_USER = "NOVARIUSIRC_USER"
ENV_NETWORK_REALNAME = "NOVARIUSIRC_REALNAME"
ENV_NETWORK_CHANNELS = "NOVARIUSIRC_CHANNELS"
ENV_NETWORK_BIND_IP = "NOVARIUSIRC_BIND_IP"
ENV_NETWORK_BIND_HOSTNAME = "NOVARIUSIRC_BIND_HOSTNAME"

ENV_AUTH_SASL_USERNAME = "NOVARIUSIRC_SASL_USERNAME"
ENV_AUTH_SASL_PASSWORD = "NOVARIUSIRC_SASL_PASSWORD"
ENV_AUTH_SASL_ENABLED = "NOVARIUSIRC_SASL_ENABLED"
ENV_AUTH_SASL_MECHANISM = "NOVARIUSIRC_SASL_MECHANISM"
ENV_AUTH_NICKSERV_USERNAME = "NOVARIUSIRC_NICKSERV_USERNAME"
ENV_AUTH_NICKSERV_PASSWORD = "NOVARIUSIRC_NICKSERV_PASSWORD"
ENV_AUTH_NICKSERV_ENABLED = "NOVARIUSIRC_NICKSERV_ENABLED"
ENV_AUTH_NICKSERV_SERVICE = "NOVARIUSIRC_NICKSERV_SERVICE"
ENV_AUTH_TOTP_SECRET = "NOVARIUSIRC_TOTP_SECRET"
ENV_AUTH_CERTFP_ENABLED = "NOVARIUSIRC_CERTFP_ENABLED"
ENV_AUTH_CERTFP_CERT_FILE = "NOVARIUSIRC_CERTFP_CERT_FILE"
ENV_AUTH_CERTFP_KEY_FILE = "NOVARIUSIRC_CERTFP_KEY_FILE"

ENV_PATHS_LOG_ROOT = "NOVARIUSIRC_LOG_ROOT"
ENV_PATHS_DATA_ROOT = "NOVARIUSIRC_DATA_ROOT"


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class BotConfig(ConfigModel):
    prefix: str = "!"
    language: str = "en"

    def resolve_env(self) -> None:
        env_val = os.getenv(ENV_BOT_PREFIX)
        if env_val:
            self.prefix = env_val
        env_val = os.getenv(ENV_BOT_LANGUAGE)
        if env_val:
            self.language = env_val


class NetworkConfig(ConfigModel):
    server: str
    port: int = Field(default=6667, ge=1, le=65535)
    tls: bool = False
    bind_ip: str | None = None
    bind_hostname: str | None = None
    allow_unusual_channel_names: bool = False
    nick: str
    user: str
    realname: str
    channels: list[str] = Field(default_factory=list)
    name: str | None = (
        None  # Optional override für Netzwerknamen (auto-detect via 005 NETWORK=)
    )
    reconnect_delays: list[int] = Field(default_factory=lambda: [10, 20, 40, 80])
    connect_timeout_seconds: float = Field(default=30.0, gt=0)
    registration_timeout_seconds: float = Field(default=60.0, gt=0)
    idle_timeout_seconds: float = Field(default=300.0, gt=0)
    ircv3_enabled: bool = True
    ircv3_capabilities: list[str] = Field(
        default_factory=lambda: [
            "account-notify",
            "account-tag",
            "away-notify",
            "chghost",
            "extended-join",
            "invite-notify",
            "message-tags",
            "multi-prefix",
            "server-time",
            "userhost-in-names",
        ]
    )
    send_rate_per_second: float = Field(default=1.0, gt=0)
    send_burst: int = Field(default=4, ge=1)
    send_queue_size: int = Field(default=256, ge=1)
    event_queue_size: int = Field(default=256, ge=1)

    @field_validator("reconnect_delays")
    @classmethod
    def validate_reconnect_delays(cls, value: list[int]) -> list[int]:
        if any(delay < 1 for delay in value):
            raise ValueError("reconnect delays must be positive")
        return value

    @field_validator("ircv3_capabilities")
    @classmethod
    def validate_ircv3_capabilities(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for capability in value:
            capability = capability.strip()
            if (
                not capability
                or capability.startswith("-")
                or any(character.isspace() for character in capability)
            ):
                raise ValueError(f"invalid IRCv3 capability: {capability!r}")
            if capability == "sasl":
                raise ValueError(
                    "SASL is configured through [auth], not ircv3_capabilities"
                )
            if len(f"CAP REQ :{capability}".encode()) > 510:
                raise ValueError(f"IRCv3 capability is too long: {capability!r}")
            if capability not in normalized:
                normalized.append(capability)
        return normalized

    @field_validator("nick", "user", "realname", "channels")
    @classmethod
    def reject_irc_control_characters(cls, value: Any) -> Any:
        values = value if isinstance(value, list) else [value]
        if any(any(char in item for char in "\r\n\0") for item in values):
            raise ValueError(
                "IRC identity and channel values must not contain CR, LF, or NUL"
            )
        return value

    @field_validator("channels")
    @classmethod
    def validate_channel_names(cls, value: list[str]) -> list[str]:
        allowed_prefixes = "#&+!"
        invalid = [
            channel
            for channel in value
            if (
                not channel
                or any(character.isspace() for character in channel)
                or any(character in channel for character in ",:")
                or not channel.startswith(tuple(allowed_prefixes))
            )
        ]
        if invalid:
            raise ValueError(
                "IRC channels must use a standard channel prefix and contain no spaces, commas, or colons"
            )
        return value

    def model_post_init(self, __context: Any, /) -> None:
        if self.allow_unusual_channel_names:
            return
        invalid = [
            channel
            for channel in self.channels
            if any(not (character.isalnum() or character in "-_") for character in channel[1:])
        ]
        if invalid:
            raise ValueError(
                "IRC channel names may only contain Unicode letters, numbers, hyphens, "
                "and underscores after their prefix; set allow_unusual_channel_names "
                "to enable compatibility mode"
            )

    def resolve_env(self) -> None:
        env_val = os.getenv(ENV_NETWORK_SERVER)
        if env_val:
            self.server = env_val
        env_val = os.getenv(ENV_NETWORK_NICK)
        if env_val:
            self.nick = env_val
        env_val = os.getenv(ENV_NETWORK_USER)
        if env_val:
            self.user = env_val
        env_val = os.getenv(ENV_NETWORK_REALNAME)
        if env_val:
            self.realname = env_val
        env_val = os.getenv(ENV_NETWORK_PORT)
        if env_val and env_val.isdigit():
            self.port = int(env_val)
        env_val = os.getenv(ENV_NETWORK_TLS)
        if env_val:
            self.tls = env_val.strip().lower() in {"1", "true", "yes", "on"}
        env_val = os.getenv(ENV_NETWORK_CHANNELS)
        if env_val:
            self.channels = [c.strip() for c in env_val.split(",") if c.strip()]
        env_val = os.getenv(ENV_NETWORK_BIND_IP)
        if env_val:
            self.bind_ip = env_val.strip()
        env_val = os.getenv(ENV_NETWORK_BIND_HOSTNAME)
        if env_val:
            self.bind_hostname = env_val.strip()


class AuthConfig(ConfigModel):
    sasl_enabled: bool = False
    sasl_mechanism: str = "PLAIN"
    sasl_username: str | None = None
    sasl_password: str | None = None

    nickserv_enabled: bool = False
    nickserv_service: str = "NickServ"
    nickserv_username: str | None = None
    nickserv_password: str | None = None

    certfp_enabled: bool = False
    certfp_cert_file: str | None = None
    certfp_key_file: str | None = None

    totp_secret: str | None = None
    session_timeout_seconds: int = 1800  # 30 Minuten default

    # TOTP-Parameter (RFC 6238)
    totp_digest: Literal["sha1", "sha256", "sha512"] = "sha256"
    totp_digits: int = 8  # Code-Länge (6-12)
    totp_interval: int = Field(default=30, ge=1)
    totp_valid_window: int = Field(default=4, ge=0)

    @field_validator("totp_digits")
    @classmethod
    def validate_totp_digits(cls, value: int) -> int:
        if not 6 <= value <= 12:
            raise ValueError("totp_digits must be between 6 and 12")
        return value

    def resolve_secrets(self) -> None:
        env_val = os.getenv(ENV_AUTH_SASL_ENABLED)
        if env_val:
            self.sasl_enabled = env_val.strip().lower() in {"1", "true", "yes", "on"}
        env_val = os.getenv(ENV_AUTH_SASL_MECHANISM)
        if env_val:
            self.sasl_mechanism = env_val
        env_val = os.getenv(ENV_AUTH_SASL_USERNAME)
        if env_val:
            self.sasl_username = env_val
        env_val = os.getenv(ENV_AUTH_SASL_PASSWORD)
        if env_val:
            self.sasl_password = env_val
        env_val = os.getenv(ENV_AUTH_NICKSERV_ENABLED)
        if env_val:
            self.nickserv_enabled = env_val.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        env_val = os.getenv(ENV_AUTH_NICKSERV_SERVICE)
        if env_val:
            self.nickserv_service = env_val
        env_val = os.getenv(ENV_AUTH_NICKSERV_USERNAME)
        if env_val:
            self.nickserv_username = env_val
        env_val = os.getenv(ENV_AUTH_NICKSERV_PASSWORD)
        if env_val:
            self.nickserv_password = env_val
        env_val = os.getenv(ENV_AUTH_TOTP_SECRET)
        if env_val:
            self.totp_secret = env_val
        env_val = os.getenv(ENV_AUTH_CERTFP_ENABLED)
        if env_val:
            self.certfp_enabled = env_val.strip().lower() in {"1", "true", "yes", "on"}
        env_val = os.getenv(ENV_AUTH_CERTFP_CERT_FILE)
        if env_val:
            self.certfp_cert_file = env_val
        env_val = os.getenv(ENV_AUTH_CERTFP_KEY_FILE)
        if env_val:
            self.certfp_key_file = env_val


class RoleEntry(ConfigModel):
    hostmask: str  # Pattern: nick!user@host oder *!*@*.trusted.net
    require_totp: bool = False
    totp_secret: str | None = None  # Individuelles TOTP-Secret (überschreibt global)


class RolesConfig(ConfigModel):
    owners: list[RoleEntry] = Field(default_factory=list)
    admins: list[RoleEntry] = Field(default_factory=list)


class ChannelLoggingConfig(ConfigModel):
    channel: str
    enabled: bool = True


class LoggingConfig(ConfigModel):
    level: str = "INFO"
    log_dir: str = "logs"
    timezone: str = "Europe/Berlin"
    channel_logging: list[ChannelLoggingConfig] = Field(default_factory=list)
    journald_enabled: bool = False

    @field_validator("level")
    @classmethod
    def uppercase_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {value}") from exc
        return value


class CommandsConfig(ConfigModel):
    rate_limit_seconds: float = Field(default=2.0, ge=0)


class LifecycleConfig(ConfigModel):
    module_start_timeout_seconds: float = Field(default=30.0, gt=0)
    module_stop_timeout_seconds: float = Field(default=30.0, gt=0)


class ControlConfig(ConfigModel):
    """Settings for the optional local Unix control endpoint."""

    enabled: bool = False
    socket_path: str = "./run/novariusirc.sock"


class PluginsConfig(ConfigModel):
    enabled: bool = True
    directory: str = "plugins"
    load: list[str] = Field(default_factory=list)
    settings: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @field_validator("load")
    @classmethod
    def validate_plugin_names(cls, value: list[str]) -> list[str]:
        invalid = [name for name in value if not re.fullmatch(r"[A-Za-z0-9_-]+", name)]
        if invalid:
            raise ValueError(f"invalid plugin names: {', '.join(invalid)}")
        return list(dict.fromkeys(value))


class FeedDefinition(ConfigModel):
    name: str
    url: str
    channel: str | None = None
    channels: list[str] = Field(default_factory=list)
    enabled: bool = True
    template: str | None = None
    min_interval_seconds: int | None = Field(default=None, ge=0)
    per_channel_interval: dict[str, int] = Field(default_factory=dict)
    max_items_per_poll: int | None = Field(default=None, ge=1)
    max_items_per_manual: int | None = Field(default=None, ge=1)

    @field_validator("channels", mode="after")
    @classmethod
    def ensure_channel_targets(cls, value: list[str], info) -> list[str]:
        channel = info.data.get("channel")
        if channel:
            value = [channel] if channel not in value else value
        if not value:
            raise ValueError(
                "feeds.feeds[].channel or feeds.feeds[].channels must be set"
            )
        return value

    @field_validator("per_channel_interval")
    @classmethod
    def validate_channel_intervals(cls, value: dict[str, int]) -> dict[str, int]:
        if any(interval < 0 for interval in value.values()):
            raise ValueError("per-channel feed intervals must not be negative")
        return value


class FeedsConfig(ConfigModel):
    enabled: bool = True
    max_feeds: int = Field(default=32, ge=1)
    max_items_per_feed: int = Field(default=64, ge=1)
    max_items_per_poll: int = Field(default=2, ge=1)
    max_items_per_manual: int = Field(default=4, ge=1)
    refresh_interval: int = Field(default=300, ge=1)
    http_timeout: int = Field(default=10, ge=1)
    max_body_size: int = Field(default=256 * 1024, ge=1024)
    user_agents: list[str] = Field(default_factory=list)
    user_agent_rotate: Literal["list", "random", "fixed"] = "list"
    tls_allow_legacy: bool = False
    tls_ca_file: str | None = None
    tls_ca_dir: str | None = None
    tls_cert_file: str | None = None
    tls_key_file: str | None = None
    feeds: list[FeedDefinition] = Field(default_factory=list)

    @field_validator(
        "tls_ca_file", "tls_ca_dir", "tls_cert_file", "tls_key_file", mode="before"
    )
    @classmethod
    def empty_path_is_none(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value


class ModerationRateLimitConfig(ConfigModel):
    enabled: bool = False
    messages_per_minute: int = Field(default=5, ge=1)
    action: Literal["warn", "mute", "kick", "ban"] = "warn"


class ModerationSpamConfig(ConfigModel):
    enabled: bool = False
    threshold: int = Field(default=3, ge=2)
    action: Literal["warn", "mute", "kick", "ban"] = "mute"
    duration_seconds: int = Field(default=300, ge=1)


class ModerationCapsConfig(ConfigModel):
    enabled: bool = False
    threshold_percent: int = Field(default=80, ge=1, le=100)
    action: Literal["warn", "mute", "kick", "ban"] = "warn"


class ModerationBadwordsConfig(ConfigModel):
    enabled: bool = False
    action: Literal["warn", "mute", "kick", "ban"] = "warn"
    list: builtins.list[str] = Field(default_factory=list)


class ModerationWarningsConfig(ConfigModel):
    enabled: bool = True
    to_kick: int = Field(default=3, ge=1)
    to_ban: int = Field(default=5, ge=1)

    @field_validator("to_ban")
    @classmethod
    def ban_after_kick(cls, value: int, info) -> int:
        if value < info.data.get("to_kick", 3):
            raise ValueError("to_ban must be greater than or equal to to_kick")
        return value


class ModerationConfig(ConfigModel):
    enabled: bool = True
    log_file: str = "logs/moderation/moderation.log"
    rate_limit: ModerationRateLimitConfig = Field(
        default_factory=ModerationRateLimitConfig
    )
    spam: ModerationSpamConfig = Field(default_factory=ModerationSpamConfig)
    caps: ModerationCapsConfig = Field(default_factory=ModerationCapsConfig)
    badwords: ModerationBadwordsConfig = Field(default_factory=ModerationBadwordsConfig)
    warnings: ModerationWarningsConfig = Field(default_factory=ModerationWarningsConfig)
    channels: dict[str, dict[str, Any]] = Field(default_factory=dict)


class WorkerConfig(ConfigModel):
    processes: int = Field(default=2, ge=1)


class PathsConfig(ConfigModel):
    log_root: str = "./logs"
    data_root: str = "./data"

    def resolve_env(self) -> None:
        env_val = os.getenv(ENV_PATHS_LOG_ROOT)
        if env_val:
            self.log_root = env_val
        env_val = os.getenv(ENV_PATHS_DATA_ROOT)
        if env_val:
            self.data_root = env_val


class IncludesConfig(ConfigModel):
    files: list[str] = Field(default_factory=lambda: list(DEFAULT_INCLUDE_FILES))


class ModulesConfig(ConfigModel):
    enabled: list[str] = Field(default_factory=lambda: ["rss_announcer"])

    @field_validator("enabled")
    @classmethod
    def validate_module_names(cls, value: list[str]) -> list[str]:
        invalid = [name for name in value if not re.fullmatch(r"[A-Za-z0-9_]+", name)]
        if invalid:
            raise ValueError(f"invalid module names: {', '.join(invalid)}")
        return list(dict.fromkeys(value))


class Config(ConfigModel):
    bot: BotConfig
    network: NetworkConfig
    includes: IncludesConfig = Field(default_factory=IncludesConfig)
    modules: ModulesConfig = Field(default_factory=ModulesConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    roles: RolesConfig = Field(default_factory=RolesConfig)
    commands: CommandsConfig = Field(default_factory=CommandsConfig)
    lifecycle: LifecycleConfig = Field(default_factory=LifecycleConfig)
    control: ControlConfig = Field(default_factory=ControlConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    feeds: FeedsConfig = Field(default_factory=FeedsConfig)
    moderation: ModerationConfig = Field(default_factory=ModerationConfig)
    workers: WorkerConfig = Field(default_factory=WorkerConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    @staticmethod
    def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in extra.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = Config._merge(merged[key], value)
            else:
                merged[key] = value
        return merged

    def validate_runtime_secrets(self) -> None:
        mechanism = self.auth.sasl_mechanism.strip().upper()
        if mechanism not in {"PLAIN", "EXTERNAL"}:
            raise ValueError(f"Unsupported SASL mechanism: {mechanism}")
        self.auth.sasl_mechanism = mechanism
        if self.auth.sasl_enabled and not self.network.tls:
            raise ValueError("SASL requires network.tls = true")
        if self.auth.certfp_enabled and not self.network.tls:
            raise ValueError("CertFP requires network.tls = true")
        if (
            self.auth.sasl_enabled
            and mechanism == "PLAIN"
            and (not self.auth.sasl_username or not self.auth.sasl_password)
        ):
            raise ValueError("SASL PLAIN requires sasl_username and sasl_password")
        if (
            self.auth.sasl_enabled
            and mechanism == "EXTERNAL"
            and (not self.auth.certfp_enabled or not self.auth.certfp_cert_file)
        ):
            raise ValueError("SASL EXTERNAL requires CertFP and certfp_cert_file")

    def resolve_relative_paths(self, base_dir: Path) -> None:
        def resolve(value: str) -> str:
            path = Path(value).expanduser()
            return str(path if path.is_absolute() else base_dir / path)

        self.plugins.directory = resolve(self.plugins.directory)
        log_root = self.paths.log_root
        if log_root == "./logs" and self.logging.log_dir != "logs":
            log_root = self.logging.log_dir
        self.paths.log_root = resolve(log_root)
        self.logging.log_dir = self.paths.log_root
        self.paths.data_root = resolve(self.paths.data_root)
        self.control.socket_path = resolve(self.control.socket_path)
        self.moderation.log_file = resolve(self.moderation.log_file)
        for attribute in ("certfp_cert_file", "certfp_key_file"):
            value = getattr(self.auth, attribute)
            if value:
                setattr(self.auth, attribute, resolve(value))
        for attribute in ("tls_ca_file", "tls_ca_dir", "tls_cert_file", "tls_key_file"):
            value = getattr(self.feeds, attribute)
            if value:
                setattr(self.feeds, attribute, resolve(value))

    @staticmethod
    def _normalize_include_files(raw: dict[str, Any]) -> tuple[list[str], bool]:
        include_files: list[str] = []
        explicitly_configured = "include" in raw or "includes" in raw

        include_value = raw.get("include")
        if isinstance(include_value, str):
            include_files.append(include_value)
        elif isinstance(include_value, list):
            include_files.extend(
                str(item) for item in include_value if isinstance(item, str)
            )

        includes_section = raw.get("includes")
        if isinstance(includes_section, dict):
            files_value = includes_section.get("files")
            if isinstance(files_value, str):
                include_files.append(files_value)
            elif isinstance(files_value, list):
                include_files.extend(
                    str(item) for item in files_value if isinstance(item, str)
                )

        if not include_files:
            include_files = list(DEFAULT_INCLUDE_FILES)

        deduped: list[str] = []
        for filename in include_files:
            filename = filename.strip()
            if filename and filename not in deduped:
                deduped.append(filename)
        return deduped, explicitly_configured

    @classmethod
    def load_from_env(cls) -> Config:
        server = os.getenv(ENV_NETWORK_SERVER)
        nick = os.getenv(ENV_NETWORK_NICK)
        missing = [
            name
            for name, value in ((ENV_NETWORK_SERVER, server), (ENV_NETWORK_NICK, nick))
            if not value
        ]
        if missing:
            raise ValueError(
                f"Missing required env vars for env-only config: {', '.join(missing)}"
            )

        user = os.getenv(ENV_NETWORK_USER) or nick
        realname = os.getenv(ENV_NETWORK_REALNAME) or nick

        raw: dict[str, Any] = {
            "bot": {},
            "network": {
                "server": server,
                "nick": nick,
                "user": user,
                "realname": realname,
            },
        }

        try:
            config = cls.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid configuration: {exc}") from exc
        config.bot.resolve_env()
        config.network.resolve_env()
        config.network = NetworkConfig.model_validate(config.network.model_dump())
        config.paths.resolve_env()
        config.auth.resolve_secrets()
        if config.auth.sasl_enabled and not config.auth.sasl_username:
            config.auth.sasl_username = config.network.nick
        if config.auth.nickserv_enabled and not config.auth.nickserv_username:
            config.auth.nickserv_username = config.network.nick
        config.validate_runtime_secrets()
        config.resolve_relative_paths(Path.cwd())
        return config

    @classmethod
    def load(cls, path: str | Path) -> Config:
        path_str = str(path)
        if path_str.lower() in {"env", "environment", "-"}:
            return cls.load_from_env()

        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration path not found: {config_path}")

        base_file = config_path / "config.toml" if config_path.is_dir() else config_path
        if not base_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {base_file}")

        with base_file.open("rb") as fh:
            raw: dict[str, Any] = tomllib.load(fh)

        # Load configured fragments from the same directory
        config_dir = base_file.parent
        include_files, includes_are_explicit = cls._normalize_include_files(raw)
        raw.pop("include", None)
        for filename in include_files:
            extra_file = config_dir / filename
            if not extra_file.exists():
                if includes_are_explicit:
                    raise FileNotFoundError(f"Included configuration file not found: {extra_file}")
                continue
            with extra_file.open("rb") as fh:
                extra_raw = tomllib.load(fh)
            raw = cls._merge(raw, extra_raw)

        try:
            config = cls.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid configuration: {exc}") from exc
        config.bot.resolve_env()
        config.network.resolve_env()
        config.network = NetworkConfig.model_validate(config.network.model_dump())
        config.paths.resolve_env()
        config.auth.resolve_secrets()
        if config.auth.sasl_enabled and not config.auth.sasl_username:
            config.auth.sasl_username = config.network.nick
        if config.auth.nickserv_enabled and not config.auth.nickserv_username:
            config.auth.nickserv_username = config.network.nick
        config.validate_runtime_secrets()
        config.resolve_relative_paths(config_dir)
        return config


def load_config(path: str | Path) -> Config:
    return Config.load(path)
