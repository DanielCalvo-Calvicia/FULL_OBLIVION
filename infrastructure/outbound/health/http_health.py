"""Adapter of HealthPort: ``/health`` (the process answers) then ``/available`` (usable)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from application.ports.outbound.health_port import HealthPort
from domain.entities.service_spec import ServiceSpec

UNAVAILABLE_GRACE_SECONDS = 15.0


def _get(url: str, timeout: float = 3.0) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - http(s) URLs from config
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        return 0, str(error).encode()


def check(base_url: str, spec: ServiceSpec) -> tuple[bool, str]:
    """``(ok, detail)``; the detail names the stage that failed."""
    status, body = _get(base_url + spec.health)
    if status != 200:
        return False, "health: " + (f"HTTP {status}" if status else f"no answer ({body.decode(errors='ignore')[:80]})")
    if spec.ready:
        status, body = _get(base_url + spec.ready)
        if status != 200:
            return False, f"available: HTTP {status}"
        try:
            data = json.loads(body).get("data")
        except ValueError:
            data = None
        if isinstance(data, dict) and data.get("is_available") is False:
            return False, f"available: {data.get('reason') or 'not available'}"
    return True, "healthy" + (" and available" if spec.ready else "")


def wait(
    base_url: str, spec: ServiceSpec, timeout: float, interval: float = 0.5,
    unavailable_grace: float = UNAVAILABLE_GRACE_SECONDS,
) -> tuple[bool, str]:
    """Wait for ``check`` to pass. A process that answers but reports itself unavailable (no audio device, say)
    gets only ``unavailable_grace`` seconds, so it does not hold up the services after it."""
    start = time.monotonic()
    deadline = start + timeout
    answered_at: float | None = None
    ok, detail = check(base_url, spec)
    while not ok and time.monotonic() < deadline:
        if detail.startswith("available:"):
            answered_at = answered_at if answered_at is not None else time.monotonic()
            if time.monotonic() - answered_at >= unavailable_grace:
                break
        else:
            answered_at = None
        time.sleep(interval)
        ok, detail = check(base_url, spec)
    return ok, detail


class HttpHealth(HealthPort):
    def check(self, base_url: str, spec: ServiceSpec) -> tuple[bool, str]:
        return check(base_url, spec)

    def wait(self, base_url: str, spec: ServiceSpec, timeout: float) -> tuple[bool, str]:
        return wait(base_url, spec, timeout)
