"""health.wait gives a reachable-but-unavailable service only a short grace period."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from infrastructure.outbound.health import http_health as health
from domain.entities.service_spec import ServiceSpec


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = {} if self.path == "/health" else {"data": {"is_available": False, "reason": "no device"}}
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(raw)


def test_unavailable_service_does_not_use_the_whole_timeout():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        spec = ServiceSpec.__new__(ServiceSpec)
        object.__setattr__(spec, "health", "/health")
        object.__setattr__(spec, "ready", "/available")
        started = time.monotonic()
        ok, detail = health.wait(
            f"http://127.0.0.1:{server.server_port}", spec, timeout=60, interval=0.05, unavailable_grace=0.3
        )
        assert not ok and detail == "available: no device"
        assert time.monotonic() - started < 10
    finally:
        server.shutdown()
