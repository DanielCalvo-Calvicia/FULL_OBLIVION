"""Reading the development workspace (a checkout of every service next to this repository) for ``oblivion compat``."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class WorkspacePort(Protocol):
    def contracts_source_version(self, workspace: Path) -> str | None: ...

    def contracts_wheels(self, folder: Path) -> list[str]:
        """File names of the ``contracts_microservice-*.whl`` wheels in the service's ``vendor/`` folder."""
        ...

    def requirements_text(self, folder: Path, relative: str) -> str | None: ...

    def env_example_port(self, folder: Path) -> int | None: ...

    def is_dir(self, folder: Path) -> bool: ...
