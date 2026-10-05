"""Where a service reads its settings from: the ``.env`` file the tool writes for it."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from domain.entities.host import Host


class EnvFilesPort(Protocol):
    def read_example(self, host: Host, name: str) -> str | None:
        """The service's own ``.env.example`` text, or None before its code was fetched."""
        ...

    def target(self, host: Host, name: str) -> Path:
        """The file the service reads its settings from (inside the clone, or an env file for a container)."""
        ...

    def write(self, host: Host, name: str, values: dict[str, str]) -> Path:
        """Write the final settings for the service and return the file. Readable by this user only (it holds keys)."""
        ...
