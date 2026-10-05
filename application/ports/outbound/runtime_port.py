"""Starting, stopping and inspecting a service, natively or in a container."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from domain.entities.host import Host


class RuntimePort(Protocol):
    @property
    def console_windows(self) -> bool:
        """True when each native service gets its own console window (Windows), so logs should be readable lines."""
        ...

    def start(self, host: Host, name: str, env: dict[str, str], env_file: Path) -> None:
        """Start the service. ``env`` only says which names the ``env_file`` defines; the settings are in the file."""
        ...

    def stop(self, host: Host, name: str) -> None: ...

    def is_running(self, host: Host, name: str) -> bool: ...
