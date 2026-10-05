"""The environment of each service on this machine: resolve it from the layers, check it, write its ``.env``."""

from __future__ import annotations

from pathlib import Path

from application.ports.outbound.env_files_port import EnvFilesPort
from application.ports.outbound.runtime_port import RuntimePort
from application.ports.outbound.shell_port import ShellPort
from domain.entities.environment import ResolvedEnv
from domain.entities.host import Host
from domain.errors import DeployError
from domain.rules.env_resolution import LAYER_COMPUTED, resolve_env


class EnvironmentService:
    def __init__(self, host: Host, env_files: EnvFilesPort, runtime: RuntimePort, shell: ShellPort) -> None:
        self._host = host
        self._env_files = env_files
        self._runtime = runtime
        self._shell = shell

    def resolve(self, name: str) -> ResolvedEnv:
        resolved = resolve_env(self._host, name, self._env_files.read_example(self._host, name))
        if (
            self._host.services[name].runtime == "native"
            and self._runtime.console_windows
            and "LOG_FORMAT" not in resolved.values
        ):
            resolved.set(LAYER_COMPUTED, "LOG_FORMAT", "console")  # readable lines in the service's own window
        return resolved

    def target(self, name: str) -> Path:
        return self._env_files.target(self._host, name)

    def write(self, name: str) -> dict[str, str]:
        """Resolve and write the service's ``.env``. Raises DeployError when a required value is missing."""
        resolved = self.resolve(name)
        if resolved.errors:
            raise DeployError("\n".join(resolved.errors))
        for warning in resolved.warnings:
            self._shell.say(f"warning: {warning}")
        if self._shell.dry_run:
            self._shell.say(f"[dry-run] write {self.target(name)} ({len(resolved.values)} variables)")
        else:
            self._env_files.write(self._host, name, resolved.values)
        return resolved.values
