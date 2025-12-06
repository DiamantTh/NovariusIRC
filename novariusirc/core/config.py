"""Configuration loading and validation."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator


class BotConfig(BaseModel):
    profile: str = "default"
    prefix: str = "!"
    language: str = "en"


class NetworkConfig(BaseModel):
    server: str
    port: int = 6667
    tls: bool = False
    nick: str
    user: str
    realname: str
    channels: List[str] = Field(default_factory=list)
    reconnect_delays: List[int] = Field(default_factory=lambda: [10, 20, 40, 80])


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
    data_root: str = "./data"


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

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with config_path.open("rb") as fh:
            raw = tomllib.load(fh)
        try:
            config = cls.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid configuration: {exc}") from exc
        config.auth.resolve_secrets()
        return config


def load_config(path: str | Path) -> Config:
    return Config.load(path)
