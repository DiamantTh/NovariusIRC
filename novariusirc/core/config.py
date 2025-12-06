"""Configuration loading and validation."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator


class BotConfig(BaseModel):
    profile: str = "default"
    prefix: str = "!"
    prefix_env: Optional[str] = None
    language: str = "en"
    language_env: Optional[str] = None

    def resolve_env(self) -> None:
        if self.prefix_env:
            env_val = os.getenv(self.prefix_env)
            if env_val:
                self.prefix = env_val
        if self.language_env:
            env_val = os.getenv(self.language_env)
            if env_val:
                self.language = env_val


class NetworkConfig(BaseModel):
    server: str
    server_env: Optional[str] = None
    port: int = 6667
    port_env: Optional[str] = None
    tls: bool = False
    tls_env: Optional[str] = None
    nick: str
    nick_env: Optional[str] = None
    user: str
    user_env: Optional[str] = None
    realname: str
    realname_env: Optional[str] = None
    channels: List[str] = Field(default_factory=list)
    channels_env: Optional[str] = None
    reconnect_delays: List[int] = Field(default_factory=lambda: [10, 20, 40, 80])

    def resolve_env(self) -> None:
        def set_from_env(field: str, env_name: Optional[str]) -> None:
            if not env_name:
                return
            env_val = os.getenv(env_name)
            if env_val:
                setattr(self, field, env_val)

        set_from_env("server", self.server_env)
        set_from_env("nick", self.nick_env)
        set_from_env("user", self.user_env)
        set_from_env("realname", self.realname_env)

        if self.port_env:
            env_val = os.getenv(self.port_env)
            if env_val and env_val.isdigit():
                self.port = int(env_val)

        if self.tls_env:
            env_val = os.getenv(self.tls_env)
            if env_val:
                self.tls = env_val.strip().lower() in {"1", "true", "yes", "on"}

        if self.channels_env:
            env_val = os.getenv(self.channels_env)
            if env_val:
                self.channels = [c.strip() for c in env_val.split(",") if c.strip()]


class AuthConfig(BaseModel):
    sasl_enabled: bool = False
    sasl_mechanism: str = "PLAIN"
    sasl_username: Optional[str] = None
    sasl_password_env: Optional[str] = None
    sasl_password: Optional[str] = None

    nickserv_enabled: bool = False
    nickserv_service: str = "NickServ"
    nickserv_username: Optional[str] = None
    nickserv_password_env: Optional[str] = None
    nickserv_password: Optional[str] = None

    totp_env: Optional[str] = None

    def resolve_secrets(self) -> None:
        if not self.sasl_password and self.sasl_password_env:
            self.sasl_password = os.getenv(self.sasl_password_env)
        if not self.nickserv_password and self.nickserv_password_env:
            self.nickserv_password = os.getenv(self.nickserv_password_env)


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
    language: Optional[str] = None


class FeedsConfig(BaseModel):
    enabled: bool = True
    max_feeds: int = 32
    max_items_per_feed: int = 64
    refresh_interval: int = 300
    http_timeout: int = 10
    max_body_size: int = 256 * 1024
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
    log_root_env: Optional[str] = None
    data_root: str = "./data"
    data_root_env: Optional[str] = None

    def resolve_env(self) -> None:
        if self.log_root_env:
            env_val = os.getenv(self.log_root_env)
            if env_val:
                self.log_root = env_val
        if self.data_root_env:
            env_val = os.getenv(self.data_root_env)
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
    def load(cls, path: str | Path) -> "Config":
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        base_file = config_path / "config.toml" if config_path.is_dir() else config_path
        if not base_file.exists():
            raise FileNotFoundError(f"Base config file not found: {base_file}")

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
        return config


def load_config(path: str | Path) -> Config:
    return Config.load(path)
