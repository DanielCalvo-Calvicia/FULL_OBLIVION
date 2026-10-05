"""Every external command goes through this port, so ``--dry-run`` can show what would happen."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol


class ShellPort(Protocol):
    dry_run: bool
    apt_updated: bool  # `apt-get update` runs once per invocation, before the first install

    def say(self, message: str) -> None: ...

    def run(
        self,
        command: Sequence[str | Path],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
        capture: bool = False,
        mutating: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command. ``mutating=False`` marks read-only queries that also run in a dry run."""
        ...

    def python_of(self, venv: Path) -> Path: ...
