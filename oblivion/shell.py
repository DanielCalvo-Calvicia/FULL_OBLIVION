"""Every external command goes through here, so ``--dry-run`` can show what would happen."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from .config import DeployError


class Shell:
    def __init__(self, dry_run: bool = False, echo: bool = True) -> None:
        self.dry_run = dry_run
        self.echo = echo

    def say(self, message: str) -> None:
        print(message, flush=True)

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
        text = " ".join(str(part) for part in command)
        if self.dry_run and mutating:
            self.say(f"[dry-run] {text}" + (f"   (in {cwd})" if cwd else ""))
            return subprocess.CompletedProcess(list(map(str, command)), 0, "", "")
        if self.echo and mutating:
            self.say(f"$ {text}")
        try:
            result = subprocess.run(
                [str(part) for part in command],
                cwd=str(cwd) if cwd else None,
                env=dict(env) if env is not None else None,
                text=True,
                capture_output=capture,
                check=False,
            )
        except FileNotFoundError as error:
            raise DeployError(f"command not found: {command[0]} ({error})") from error
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-600:]
            raise DeployError(f"command failed ({result.returncode}): {text}" + (f"\n{detail}" if detail else ""))
        return result

    def python_of(self, venv: Path) -> Path:
        return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
