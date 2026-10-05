"""Turning a fetched service repo into something that runs: virtualenv, dependencies, shared libraries, container image."""

from __future__ import annotations

from typing import Protocol

from domain.entities.catalogue import Catalogue
from domain.entities.host import Host


class InstallerPort(Protocol):
    def install_native(
        self, host: Host, catalogue: Catalogue, name: str, *, previous_fingerprint: str | None, system_deps: bool
    ) -> tuple[str, list[str]]:
        """Create the virtualenv and install dependencies. Returns ``(fingerprint, warnings)``."""
        ...

    def build_image(self, host: Host, catalogue: Catalogue, name: str) -> None:
        """Build the Docker image of a service whose runtime is ``docker``."""
        ...

    def check_python(self, host: Host, selected: list[str]) -> list[str]:
        """Errors for native services whose dependencies need a newer Python than the one that will build their venv."""
        ...

    def check_libraries(self, catalogue: Catalogue, libraries: set[str]) -> tuple[list[str], list[str]]:
        """``(errors, warnings)`` for the shared libraries the selected services need. Nothing is installed."""
        ...
