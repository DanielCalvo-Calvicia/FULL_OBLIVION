"""Adapter of WorkspacePort: reads the development workspace (a checkout of every service) for ``oblivion compat``."""

from __future__ import annotations

import re
from pathlib import Path

from application.ports.outbound.workspace_port import WorkspacePort

_PORT_NAMES = ("SERVICE_PORT", "AI_AGENT_PORT")


class WorkspaceFiles(WorkspacePort):
    def contracts_source_version(self, workspace: Path) -> str | None:
        pyproject = workspace / "contracts" / "pyproject.toml"
        if not pyproject.exists():
            return None
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
        return match.group(1) if match else None

    def contracts_wheels(self, folder: Path) -> list[str]:
        vendor = folder / "vendor"
        return sorted(p.name for p in vendor.glob("contracts_microservice-*.whl")) if vendor.is_dir() else []

    def requirements_text(self, folder: Path, relative: str) -> str | None:
        path = folder / relative
        return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else None

    def env_example_port(self, folder: Path) -> int | None:
        example = folder / ".env.example"
        if not example.exists():
            return None
        for line in example.read_text(encoding="utf-8", errors="ignore").splitlines():
            name, _, value = line.partition("=")
            if name.strip() in _PORT_NAMES and value.strip().split("#")[0].strip().isdigit():
                return int(value.strip().split("#")[0].strip())
        return None

    def is_dir(self, folder: Path) -> bool:
        return folder.is_dir()
