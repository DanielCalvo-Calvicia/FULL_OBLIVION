"""Adapter of RuntimePort: a service runs natively or in Docker, whichever its ``runtime`` says."""

from __future__ import annotations

from pathlib import Path

from application.ports.outbound.runtime_port import RuntimePort
from application.ports.outbound.shell_port import ShellPort
from domain.entities.host import Host
from infrastructure.outbound.runtime import docker_runtime, native_runtime


class ProcessRuntime(RuntimePort):
    def __init__(self, shell: ShellPort) -> None:
        self._shell = shell

    @property
    def console_windows(self) -> bool:
        return native_runtime.uses_console_window()

    def start(self, host: Host, name: str, env: dict[str, str], env_file: Path) -> None:
        if host.services[name].runtime == "docker":
            docker_runtime.require_docker()
            docker_runtime.start(self._shell, host, name, env_file)
        else:
            native_runtime.start(self._shell, host, name, env, env_file)

    def stop(self, host: Host, name: str) -> None:
        if host.services[name].runtime == "docker":
            docker_runtime.stop(self._shell, host, name)
        else:
            native_runtime.stop(self._shell, host, name)

    def is_running(self, host: Host, name: str) -> bool:
        if host.services[name].runtime == "docker":
            return docker_runtime.is_running(self._shell, name)
        return native_runtime.is_running(host, name)
