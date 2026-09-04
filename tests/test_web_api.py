from __future__ import annotations

import json
import logging
import os
import time
from types import SimpleNamespace

from tornado.testing import AsyncHTTPTestCase

from novariusirc.core.config import WebAPIConfig
from novariusirc.core.web_api import (
    WebAPIServer,
    _process_memory_status,
    _psutil_monitoring_status,
    _redact_dsn,
)


def test_status_dsn_redaction_removes_credentials_and_parameters() -> None:
    assert (
        _redact_dsn("postgresql+psycopg://monitor:secret@example.test:5432/novarius?sslmode=require")
        == "postgresql+psycopg://example.test:5432/novarius"
    )
    assert _redact_dsn("not a DSN") == "configured"


def test_process_memory_status_reads_proc_and_cgroup_v2(tmp_path) -> None:
    proc_root = tmp_path / "proc"
    cgroup_root = tmp_path / "cgroup"
    proc_root.mkdir()
    cgroup_root.mkdir()
    (proc_root / "statm").write_text("10 4 0 0 0 0 0\n", encoding="ascii")
    (cgroup_root / "memory.current").write_text("1234\n", encoding="ascii")
    (cgroup_root / "memory.max").write_text("max\n", encoding="ascii")

    status = _process_memory_status(proc_root, cgroup_root)

    assert status["resident_bytes"] == 4 * os.sysconf("SC_PAGE_SIZE")
    assert status["virtual_bytes"] == 10 * os.sysconf("SC_PAGE_SIZE")
    assert status["cgroup_current_bytes"] == 1234
    assert status["cgroup_limit_bytes"] is None


def test_psutil_monitoring_is_optional() -> None:
    assert _psutil_monitoring_status() is None


class TestMonitoringRoutes(AsyncHTTPTestCase):
    def setUp(self) -> None:
        self.client_state = SimpleNamespace(
            is_connected=False,
            is_registered=False,
            network_name="example.test",
            current_nick="NovariusBot",
            send_queue_depth=2,
            send_queue_capacity=256,
            event_queue_depth=3,
            event_queue_capacity=128,
        )
        self.feeds = SimpleNamespace(
            config=SimpleNamespace(enabled=True),
            is_running=True,
            feed_definitions={"https://example.test/feed.xml": object()},
        )
        self.web_api = WebAPIServer(
            WebAPIConfig(enabled=True),
            self.client_state,  # type: ignore[arg-type]
            self.feeds,  # type: ignore[arg-type]
            None,
            time.monotonic() - 3,
            logging.getLogger("test.web_api"),
        )
        super().setUp()

    def get_app(self):
        return self.web_api.application()

    def test_health_is_available_before_irc_registration(self) -> None:
        response = self.fetch("/_health")

        assert response.code == 200
        assert json.loads(response.body) == {"status": "ok", "service": "novariusirc"}
        assert response.headers["Cache-Control"] == "no-store"

    def test_readiness_waits_for_irc_registration(self) -> None:
        response = self.fetch("/_ready")
        assert response.code == 503
        assert json.loads(response.body)["status"] == "not_ready"

        self.client_state.is_connected = True
        self.client_state.is_registered = True
        response = self.fetch("/_ready")

        assert response.code == 200
        assert json.loads(response.body) == {
            "status": "ready",
            "irc": {"connected": True, "registered": True},
        }

    def test_status_exposes_operational_data_without_secrets(self) -> None:
        response = self.fetch("/v1/status")
        payload = json.loads(response.body)

        assert response.code == 200
        assert payload["irc"] == {
            "connected": False,
            "registered": False,
            "network": "example.test",
            "nick": "NovariusBot",
            "server": None,
            "port": None,
            "tls": None,
            "configured_channels": None,
        }
        assert payload["feeds"] == {"enabled": True, "running": True, "configured": 1}
        assert payload["bot"] == {"name": None, "command_prefix": None, "language": None}
        assert payload["database"] == {
            "enabled": False,
            "backend": None,
            "schema": None,
            "location": None,
            "settings": {},
        }
        assert payload["backups"] == {
            "directory": None,
            "last_successful_at": None,
            "last_successful_file": None,
        }
        assert payload["modules"] == {"built_in": [], "external": []}
        assert payload["paths"] == {"logs": None, "data": None}
        assert payload["runtime"]["python"]
        assert payload["runtime"]["platform"]
        assert set(payload["runtime"]["memory"]) == {
            "resident_bytes",
            "virtual_bytes",
            "cgroup_current_bytes",
            "cgroup_limit_bytes",
        }
        assert payload["runtime"]["extended_monitoring"] is None
        assert payload["queues"] == {
            "send": {"depth": 2, "capacity": 256},
            "events": {"depth": 3, "capacity": 128},
        }
        assert payload["uptime_seconds"] >= 3

    def test_optional_network_allowlist_uses_the_tcp_peer(self) -> None:
        self.web_api.config.allowed_networks = ["192.0.2.0/24"]
        response = self.fetch("/v1/status")
        assert response.code == 403
        assert json.loads(response.body) == {"status": "forbidden"}

        self.web_api.config.allowed_networks = ["127.0.0.1"]
        response = self.fetch("/v1/status")
        assert response.code == 200

    def test_unknown_route_is_not_found(self) -> None:
        response = self.fetch("/not-here")

        assert response.code == 404
        assert json.loads(response.body) == {"status": "not_found"}
