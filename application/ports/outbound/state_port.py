"""What is deployed on this machine: branch, commit and install fingerprint per service."""

from __future__ import annotations

from typing import Any, Protocol


class StatePort(Protocol):
    def get(self, name: str) -> dict[str, Any]: ...

    def update(self, name: str, **fields: Any) -> None: ...
