"""What is deployed on this machine: branch, commit and install fingerprint per service."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class State:
    def __init__(self, directory: Path) -> None:
        self._path = directory / "state.json"
        try:
            self._data: dict[str, dict[str, Any]] = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._data = {}

    def get(self, name: str) -> dict[str, Any]:
        return dict(self._data.get(name, {}))

    def update(self, name: str, **fields: Any) -> None:
        entry = self._data.setdefault(name, {})
        entry.update(fields, deployed_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
