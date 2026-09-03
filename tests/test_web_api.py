from __future__ import annotations

import json
import logging
import time
from types import SimpleNamespace

from tornado.testing import AsyncHTTPTestCase

from novariusirc.core.config import WebAPIConfig
from novariusirc.core.web_api import WebAPIServer


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
        }
        assert payload["feeds"] == {"enabled": True, "running": True, "configured": 1}
        assert payload["database"] == {"enabled": False, "backend": None}
        assert payload["queues"] == {
            "send": {"depth": 2, "capacity": 256},
            "events": {"depth": 3, "capacity": 128},
        }
        assert payload["uptime_seconds"] >= 3

    def test_unknown_route_is_not_found(self) -> None:
        response = self.fetch("/not-here")

        assert response.code == 404
        assert json.loads(response.body) == {"status": "not_found"}
