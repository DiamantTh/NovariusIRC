"""Configuration loading and validation."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

ENV_BOT_PREFIX = "NOVARIUSIRC_PREFIX"
ENV_BOT_LANGUAGE = "NOVARIUSIRC_LANG"

ENV_NETWORK_SERVER = "NOVARIUSIRC_SERVER"
ENV_NETWORK_PORT = "NOVARIUSIRC_PORT"
ENV_NETWORK_TLS = "NOVARIUSIRC_TLS"
ENV_NETWORK_NICK = "NOVARIUSIRC_NICK"
ENV_NETWORK_USER = "NOVARIUSIRC_USER"
ENV_NETWORK_REALNAME = "NOVARIUSIRC_REALNAME"
ENV_NETWORK_CHANNELS = "NOVARIUSIRC_CHANNELS"

ENV_AUTH_SASL_USERNAME = "NOVARIUSIRC_SASL_USERNAME"
ENV_AUTH_SASL_PASSWORD = "NOVARIUSIRC_SASL_PASSWORD"
ENV_AUTH_SASL_ENABLED = "NOVARIUSIRC_SASL_ENABLED"
ENV_AUTH_SASL_MECHANISM = "NOVARIUSIRC_SASL_MECHANISM"
ENV_AUTH_NICKSERV_USERNAME = "NOVARIUSIRC_NICKSERV_USERNAME"
ENV_AUTH_NICKSERV_PASSWORD = "NOVARIUSIRC_NICKSERV_PASSWORD"
ENV_AUTH_NICKSERV_ENABLED = "NOVARIUSIRC_NICKSERV_ENABLED"
ENV_AUTH_NICKSERV_SERVICE = "NOVARIUSIRC_NICKSERV_SERVICE"
ENV_AUTH_TOTP_SECRET = "NOVARIUSIRC_TOTP_SECRET"

ENV_PATHS_LOG_ROOT = "NOVARIUSIRC_LOG_ROOT"
ENV_PATHS_DATA_ROOT = "NOVARIUSIRC_DATA_ROOT"


class BotConfig(BaseModel):
    profile: str = "default"
    prefix: str = "!"
    language: str = "en"

    def resolve_env(self) -> None:
        env_val = os.getenv(ENV_BOT_PREFIX)
        if env_val:
            self.prefix = env_val
        env_val = os.getenv(ENV_BOT_LANGUAGE)
        if env_val:
            self.language = env_val


class NetworkConfig(BaseModel):
    server: str
    port: int = 6667
    tls: bool = False
    nick: str
    user: str
    realname: str
    channels: List[str] = Field(default_factory=list)
    reconnect_delays: List[int] = Field(default_factory=lambda: [10, 20, 40, 80])

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


class AuthConfig(BaseModel):
    sasl_enabled: bool = False
    sasl_mechanism: str = "PLAIN"
    sasl_username: Optional[str] = None
    sasl_password: Optional[str] = None

    nickserv_enabled: bool = False
    nickserv_service: str = "NickServ"
    nickserv_username: Optional[str] = None
    nickserv_password: Optional[str] = None

    totp_secret: Optional[str] = None

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
            self.nickserv_enabled = env_val.strip().lower() in {"1", "true", "yes", "on"}
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


class RoleEntry(BaseModel):
    nick: str
    require_totp: bool = False


class RolesConfig(BaseModel):
    owners: List[RoleEntry] = Field(default_factory=list)
    admins: List[str] = Field(default_factory=list)


class ChannelLoggingConfig(BaseModel):
    channel: str
    enabled: bool = True


class LoggingConfig(BaseModel):
    level: str = "INFO"
    log_dir: str = "logs"
    channel_logging: List[ChannelLoggingConfig] = Field(default_factory=list)
    journald_enabled: bool = False

    @field_validator("level")
    @classmethod
    def uppercase_level(cls, value: str) -> str:
        return value.upper()


class FeedDefinition(BaseModel):
    name: str
    url: str
    channel: str
    enabled: bool = True
    template: Optional[str] = None


class FeedsConfig(BaseModel):
    enabled: bool = True
    max_feeds: int = 32
    max_items_per_feed: int = 64
    refresh_interval: int = 300
    http_timeout: int = 10
    max_body_size: int = 256 * 1024
    user_agents: List[str] = Field(default_factory=list)
    user_agent_rotate: str = "list"  # list|random|fixed
    tls_allow_legacy: bool = False
    tls_ca_file: Optional[str] = None
    tls_ca_dir: Optional[str] = None
    tls_cert_file: Optional[str] = None
    tls_key_file: Optional[str] = None
    feeds: List[FeedDefinition] = Field(default_factory=list)


class FloodThreshold(BaseModel):
    messages: int = 5
    per_seconds: int = 10


class ModerationConfig(BaseModel):
    mode: str = "warn"  # off|warn|enforce (MVP supports warn)
    flood_threshold: FloodThreshold = Field(default_factory=FloodThreshold)
    warn_targets: List[str] = Field(default_factory=list)

    @field_validator("mode")
    @classmethod
    def valid_mode(cls, value: str) -> str:
        allowed = {"off", "warn", "enforce"}
        mode = value.lower()
        if mode not in allowed:
            raise ValueError(f"moderation.mode must be one of {allowed}")
        return mode


class WorkerConfig(BaseModel):
    processes: int = 2
    long_lived_enabled: bool = False


class PathsConfig(BaseModel):
    log_root: str = "./logs"
    data_root: str = "./data"

    def resolve_env(self) -> None:
        env_val = os.getenv(ENV_PATHS_LOG_ROOT)
        if env_val:
            self.log_root = env_val
        env_val = os.getenv(ENV_PATHS_DATA_ROOT)
        if env_val:
            self.data_root = env_val


class Config(BaseModel):
    bot: BotConfig
    network: NetworkConfig
    auth: AuthConfig = Field(default_factory=AuthConfig)
    roles: RolesConfig = Field(default_factory=RolesConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    feeds: FeedsConfig = Field(default_factory=FeedsConfig)
    moderation: ModerationConfig = Field(default_factory=ModerationConfig)
    workers: WorkerConfig = Field(default_factory=WorkerConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    @staticmethod
    def _merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base)
        for key, value in extra.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = Config._merge(merged[key], value)
            else:
                merged[key] = value
        return merged

    @classmethod
    def load_from_env(cls) -> "Config":
        server = os.getenv(ENV_NETWORK_SERVER)
        nick = os.getenv(ENV_NETWORK_NICK)
        missing = [name for name, value in ((ENV_NETWORK_SERVER, server), (ENV_NETWORK_NICK, nick)) if not value]
        if missing:
            raise ValueError(f"Missing required env vars for env-only config: {', '.join(missing)}")

        user = os.getenv(ENV_NETWORK_USER) or nick
        realname = os.getenv(ENV_NETWORK_REALNAME) or nick

        raw: Dict[str, Any] = {
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
        config.paths.resolve_env()
        config.auth.resolve_secrets()
        if config.auth.sasl_enabled and not config.auth.sasl_username:
            config.auth.sasl_username = config.network.nick
        if config.auth.nickserv_enabled and not config.auth.nickserv_username:
            config.auth.nickserv_username = config.network.nick
        return config

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path_str = str(path)
        if path_str.lower() in {"env", "environment", "-"}:
            return cls.load_from_env()

        config_path = Path(path)
        if not config_path.exists():
            return cls.load_from_env()

        base_file = config_path / "config.toml" if config_path.is_dir() else config_path
        if not base_file.exists():
            return cls.load_from_env()

        with base_file.open("rb") as fh:
            raw: Dict[str, Any] = tomllib.load(fh)

        # Load optional fragments from the same directory
        config_dir = base_file.parent
        optional_files = ["feeds.toml", "moderation.toml", "workers.toml"]
        for filename in optional_files:
            extra_file = config_dir / filename
            if extra_file.exists():
                with extra_file.open("rb") as fh:
                    extra_raw = tomllib.load(fh)
                raw = cls._merge(raw, extra_raw)

        try:
            config = cls.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid configuration: {exc}") from exc
        config.bot.resolve_env()
        config.network.resolve_env()
        config.paths.resolve_env()
        config.auth.resolve_secrets()
        if config.auth.sasl_enabled and not config.auth.sasl_username:
            config.auth.sasl_username = config.network.nick
        if config.auth.nickserv_enabled and not config.auth.nickserv_username:
            config.auth.nickserv_username = config.network.nick
        return config


def load_config(path: str | Path) -> Config:
    return Config.load(path)
