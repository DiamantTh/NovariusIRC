"""Optional, read-only Tornado monitoring endpoints."""

from __future__ import annotations

import ipaddress
import logging
import os
import platform
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from tornado.httpserver import HTTPServer
from tornado.web import Application, RequestHandler

from novariusirc.version import SIMPLE_VERSION, runtime_environment

if TYPE_CHECKING:
    from .client import IRCClient
    from .config import Config, WebAPIConfig
    from .database import DatabaseBackend
    from .feeds import FeedEngine
    from .plugins import PluginManager


@dataclass(frozen=True)
class MonitoringSnapshot:
    """Read-only, secret-free runtime data shared by HTTP endpoints."""

    uptime_seconds: int
    irc_connected: bool
    irc_registered: bool
    network: str
    nick: str
    feeds_enabled: bool
    feeds_running: bool
    configured_feeds: int
    database_enabled: bool
    database_backend: str | None
    database_schema: str | None
    database_location: str | None
    database_settings: dict[str, str | int | bool]
    last_backup_at: str | None
    last_backup_file: str | None
    bot_name: str | None
    command_prefix: str | None
    language: str | None
    irc_server: str | None
    irc_port: int | None
    irc_tls: bool | None
    configured_channels: int | None
    built_in_modules: tuple[str, ...]
    external_plugins: tuple[str, ...]
    runtime: str
    python: str
    platform: str
    architecture: str
    effective_uid: int | None
    effective_gid: int | None
    log_directory: str | None
    data_directory: str | None
    backup_directory: str | None
    send_queue_depth: int
    send_queue_capacity: int
    event_queue_depth: int
    event_queue_capacity: int

    @property
    def ready(self) -> bool:
        """An IRC bot is ready only after its IRC registration completed."""
        return self.irc_registered

    def as_dict(self) -> dict[str, Any]:
        return {
            "service": "novariusirc",
            "version": SIMPLE_VERSION,
            "uptime_seconds": self.uptime_seconds,
            "bot": {
                "name": self.bot_name,
                "command_prefix": self.command_prefix,
                "language": self.language,
            },
            "irc": {
                "connected": self.irc_connected,
                "registered": self.irc_registered,
                "network": self.network,
                "nick": self.nick,
                "server": self.irc_server,
                "port": self.irc_port,
                "tls": self.irc_tls,
                "configured_channels": self.configured_channels,
            },
            "feeds": {
                "enabled": self.feeds_enabled,
                "running": self.feeds_running,
                "configured": self.configured_feeds,
            },
            "database": {
                "enabled": self.database_enabled,
                "backend": self.database_backend,
                "schema": self.database_schema,
                "location": self.database_location,
                "settings": self.database_settings,
            },
            "backups": {
                "directory": self.backup_directory,
                "last_successful_at": self.last_backup_at,
                "last_successful_file": self.last_backup_file,
            },
            "modules": {
                "built_in": list(self.built_in_modules),
                "external": list(self.external_plugins),
            },
            "runtime": {
                "environment": self.runtime,
                "python": self.python,
                "platform": self.platform,
                "architecture": self.architecture,
                "effective_uid": self.effective_uid,
                "effective_gid": self.effective_gid,
            },
            "paths": {
                "logs": self.log_directory,
                "data": self.data_directory,
            },
            "queues": {
                "send": {
                    "depth": self.send_queue_depth,
                    "capacity": self.send_queue_capacity,
                },
                "events": {
                    "depth": self.event_queue_depth,
                    "capacity": self.event_queue_capacity,
                },
            },
        }


class WebAPIServer:
    """Own the optional local Tornado listener and its monitoring routes."""

    def __init__(
        self,
        config: WebAPIConfig,
        client: IRCClient,
        feeds: FeedEngine,
        database: DatabaseBackend | None,
        start_time: float,
        logger: logging.Logger,
        backups=None,
        runtime_config: Config | None = None,
        plugins: PluginManager | None = None,
    ):
        self.config = config
        self.client = client
        self.feeds = feeds
        self.database = database
        self.backups = backups
        self.runtime_config = runtime_config
        self.plugins = plugins
        self.start_time = start_time
        self.logger = logger.getChild("web_api")
        self._server: HTTPServer | None = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def snapshot(self) -> MonitoringSnapshot:
        database_schema: str | None = None
        database_location: str | None = None
        database_settings: dict[str, str | int | bool] = {}
        if self.database is not None:
            try:
                database_status = self.database.check()
                database_schema = database_status.schema_version
                database_location = database_status.location
                database_settings = database_status.settings
            except Exception:  # Monitoring must not fail because a status probe cannot inspect SQL.
                self.logger.warning("Could not read database status for monitoring", exc_info=True)
        last_backup_at: str | None = None
        last_backup_file: str | None = None
        if self.backups is not None:
            archived = self.backups.list()
            if archived:
                newest = archived[0]
                last_backup_at = datetime.fromtimestamp(newest.stat().st_mtime, UTC).isoformat()
                last_backup_file = newest.name

        config = self.runtime_config
        external_plugins = (
            tuple(self.plugins.loader.plugins) if self.plugins and self.plugins.loader else ()
        )
        effective_uid = os.geteuid() if hasattr(os, "geteuid") else None
        effective_gid = os.getegid() if hasattr(os, "getegid") else None
        return MonitoringSnapshot(
            uptime_seconds=max(0, int(time.monotonic() - self.start_time)),
            irc_connected=self.client.is_connected,
            irc_registered=self.client.is_registered,
            network=self.client.network_name,
            nick=self.client.current_nick,
            feeds_enabled=self.feeds.config.enabled,
            feeds_running=self.feeds.is_running,
            configured_feeds=len(self.feeds.feed_definitions),
            database_enabled=self.database is not None,
            database_backend=self.database.backend_name if self.database else None,
            database_schema=database_schema,
            database_location=(
                database_location
                if self.database is not None and self.database.backend_name == "sqlite"
                else _redact_dsn(config.database.dsn) if config and config.database.dsn else None
            ),
            database_settings=database_settings,
            last_backup_at=last_backup_at,
            last_backup_file=last_backup_file,
            bot_name=config.bot.name if config else None,
            command_prefix=config.bot.prefix if config else None,
            language=config.bot.language if config else None,
            irc_server=config.network.server if config else None,
            irc_port=config.network.port if config else None,
            irc_tls=config.network.tls if config else None,
            configured_channels=len(config.network.channels) if config else None,
            built_in_modules=self.plugins.active_builtin_modules if self.plugins else (),
            external_plugins=external_plugins,
            runtime=runtime_environment(),
            python=platform.python_version(),
            platform=platform.system(),
            architecture=platform.machine(),
            effective_uid=effective_uid,
            effective_gid=effective_gid,
            log_directory=config.paths.log_root if config else None,
            data_directory=config.paths.data_root if config else None,
            backup_directory=(str(self.backups.directory) if self.backups else None),
            send_queue_depth=self.client.send_queue_depth,
            send_queue_capacity=self.client.send_queue_capacity,
            event_queue_depth=self.client.event_queue_depth,
            event_queue_capacity=self.client.event_queue_capacity,
        )

    def application(self) -> Application:
        return Application(
            [
                (r"/_health", _HealthHandler, {"web_api": self}),
                (r"/_ready", _ReadyHandler, {"web_api": self}),
                (r"/v1/status", _StatusHandler, {"web_api": self}),
            ],
            default_handler_class=_NotFoundHandler,
        )

    def allows_client(self, remote_ip: str) -> bool:
        """Check the TCP peer address, never an untrusted forwarding header."""
        if not self.config.allowed_networks:
            return True
        try:
            address = ipaddress.ip_address(remote_ip)
        except ValueError:
            return False
        return any(
            address in ipaddress.ip_network(network, strict=False)
            for network in self.config.allowed_networks
        )

    async def start(self) -> None:
        if not self.config.enabled or self._server is not None:
            return
        # Do not trust X-Forwarded-For unless a dedicated proxy integration is
        # introduced. The allowlist intentionally sees the TCP peer address.
        server = HTTPServer(self.application(), xheaders=False)
        server.listen(self.config.port, address=self.config.host)
        self._server = server
        self.logger.info("Monitoring API listening on %s:%s", self.config.host, self.config.port)

    async def stop(self) -> None:
        server = self._server
        self._server = None
        if server is None:
            return
        server.stop()
        await server.close_all_connections()


def _redact_dsn(value: str) -> str:
    """Return a useful connection target without credentials or options."""
    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.hostname:
            return "configured"
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"{parsed.scheme}://{host}{port}{parsed.path}"
    except ValueError:
        return "configured"


class _BaseHandler(RequestHandler):
    def initialize(self, web_api: WebAPIServer) -> None:
        self.web_api = web_api

    def set_default_headers(self) -> None:
        self.set_header("Cache-Control", "no-store")
        self.set_header("X-Content-Type-Options", "nosniff")

    def prepare(self) -> None:
        if not self.web_api.allows_client(self.request.remote_ip):
            self.set_status(403)
            self.finish({"status": "forbidden"})


class _HealthHandler(_BaseHandler):
    def get(self) -> None:
        self.write({"status": "ok", "service": "novariusirc"})


class _ReadyHandler(_BaseHandler):
    def get(self) -> None:
        snapshot = self.web_api.snapshot()
        if not snapshot.ready:
            self.set_status(503)
        self.write(
            {
                "status": "ready" if snapshot.ready else "not_ready",
                "irc": {"connected": snapshot.irc_connected, "registered": snapshot.irc_registered},
            }
        )


class _StatusHandler(_BaseHandler):
    def get(self) -> None:
        self.write(self.web_api.snapshot().as_dict())


class _NotFoundHandler(RequestHandler):
    def prepare(self) -> None:
        self.set_status(404)
        self.set_header("Cache-Control", "no-store")
        self.finish({"status": "not_found"})
