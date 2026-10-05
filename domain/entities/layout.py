"""A layout: which machine runs which services, and where each machine is."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Machine:
    name: str
    address: str
    services: tuple[str, ...]
    ports: dict[str, int] = field(default_factory=dict)  # only where a service does not use the catalogue's port


@dataclass(frozen=True)
class Layout:
    """The whole robot's placement, once. Every service runs on exactly one machine."""

    name: str  # the preset chosen in robot.toml, e.g. "speaker-on-pc"
    machines: dict[str, Machine]
    source: Path  # the layout file
    description: str = ""

    def machine_of(self, service: str) -> Machine | None:
        return next((m for m in self.machines.values() if service in m.services), None)
