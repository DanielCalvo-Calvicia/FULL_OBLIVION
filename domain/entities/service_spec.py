"""What a service IS: where its code lives, how it is installed and run, what it calls (``config/catalogue.toml``)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RequireRule:
    key: str
    when: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    git: str
    branch: str
    port: int
    health: str = "/health"
    ready: str | None = None
    entry: str = "main.py"
    requirements: dict[str, str] = field(default_factory=dict)
    libraries: tuple[str, ...] = ()
    apt: tuple[str, ...] = ()
    prepare: tuple[str, ...] = ()  # script (and its arguments) run with the service's python once its .env is written
    audio: bool = False
    consumes: dict[str, str] = field(default_factory=dict)
    optional_consumes: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    require: tuple[RequireRule, ...] = ()
    folder: str | None = None  # clone folder name; default <name>_microservice
    host_var: str = "SERVICE_HOST"  # env var the service reads its bind address from
    port_var: str = "SERVICE_PORT"  # env var the service reads its port from
    min_python: tuple[int, int] | None = None  # oldest Python its pinned dependencies install on
    require_any: tuple[str, ...] = ()  # at least one of these should be set, or the service cannot work
    extra_env: tuple[str, ...] = ()  # variables its code reads that no .env.example lists (glob patterns)
    internal: tuple[str, ...] = ()  # wiring constants and development switches nobody sets on a deployed machine (globs)
    dotenv: bool = True  # the service reads the .env in its own folder; False: service_runner.py reads it for it

    @property
    def repo_dir(self) -> str:
        return self.folder or f"{self.name}_microservice"
