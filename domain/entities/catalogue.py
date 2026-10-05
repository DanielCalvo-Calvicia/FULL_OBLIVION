"""The catalogue: every service the tool can deploy, and the shared libraries they need."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domain.entities.service_spec import ServiceSpec


@dataclass(frozen=True)
class Catalogue:
    services: dict[str, ServiceSpec]
    libraries: dict[str, dict[str, str]]
    base_dir: Path  # relative library paths in the catalogue are relative to this folder (the repository root)

    def names(self) -> list[str]:
        return sorted(self.services)
