"""HTTP health of a service: ``/health`` (the process answers) then ``/available`` (usable)."""

from __future__ import annotations

from typing import Protocol

from domain.entities.service_spec import ServiceSpec


class HealthPort(Protocol):
    def check(self, base_url: str, spec: ServiceSpec) -> tuple[bool, str]:
        """``(ok, detail)``; the detail names the stage that failed."""
        ...

    def wait(self, base_url: str, spec: ServiceSpec, timeout: float) -> tuple[bool, str]:
        """Wait for ``check`` to pass, up to ``timeout`` seconds."""
        ...
