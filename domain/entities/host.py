"""One machine as it will be deployed: its services, where its files go and how it reaches the other machines."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from domain.entities.service_spec import ServiceSpec

RUNTIMES = ("native", "docker")


@dataclass(frozen=True)
class EnvLayer:
    """One file's ``[env]`` table, in the order the layers are applied (a later layer wins)."""

    label: str  # how `plan` and `env` name it, e.g. "local/stt.toml"
    values: dict[str, str]
    shared: bool = False  # all.toml: the values only reach the services that use the variable


@dataclass(frozen=True)
class ServiceInstance:
    """One service as configured for one machine."""

    spec: ServiceSpec
    branch: str
    runtime: str
    port: int
    layers: tuple[EnvLayer, ...] = ()  # the settings files that apply to it, lowest priority first


@dataclass(frozen=True)
class Host:
    name: str  # the machine's name in the layout
    os_family: str  # "windows" | "linux"
    is_raspberry: bool
    workdir: Path
    bind: str
    python: str | None
    services: dict[str, ServiceInstance]
    remote: dict[str, str]  # base URL of every service that runs on ANOTHER machine
    config_dir: Path  # the config folder this host was built from (autostart passes it back)
    layout: Path | None = None  # the layout file
    extra_files: dict[str, Path] = field(default_factory=dict)  # which settings files exist, for messages

    def state_dir(self) -> Path:
        return self.workdir / "state"

    def service_dir(self, name: str) -> Path:
        return self.workdir / "services" / self.services[name].spec.repo_dir

    def venv_dir(self, name: str) -> Path:
        return self.workdir / "venvs" / name

    def log_file(self, name: str) -> Path:
        return self.workdir / "logs" / f"{name}.log"

    def pid_file(self, name: str) -> Path:
        return self.workdir / "run" / f"{name}.pid"
