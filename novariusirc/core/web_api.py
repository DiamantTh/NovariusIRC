"""Optional, read-only Tornado monitoring endpoints."""

from __future__ import annotations

import ipaddress
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tornado.httpserver import HTTPServer
from tornado.web import Application, RequestHandler

from novariusirc.version import SIMPLE_VERSION

if TYPE_CHECKING:
    from .client import IRCClient
    from .config import WebAPIConfig
    from .database import DatabaseBackend
    from .feeds import FeedEngine


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
            "irc": {
                "connected": self.irc_connected,
                "registered": self.irc_registered,
                "network": self.network,
                "nick": self.nick,
            },
            "feeds": {
                "enabled": self.feeds_enabled,
                "running": self.feeds_running,
                "configured": self.configured_feeds,
            },
            "database": {
                "enabled": self.database_enabled,
                "backend": self.database_backend,
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
    ):
        self.config = config
        self.client = client
        self.feeds = feeds
        self.database = database
        self.start_time = start_time
        self.logger = logger.getChild("web_api")
        self._server: HTTPServer | None = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def snapshot(self) -> MonitoringSnapshot:
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
