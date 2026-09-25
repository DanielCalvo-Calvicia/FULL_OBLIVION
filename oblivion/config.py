"""Registry (what the services are) and host files (what runs on one machine)."""

from __future__ import annotations

import platform
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

RUNTIMES = ("native", "docker")


class DeployError(Exception):
    """A problem the operator must fix; the CLI prints it without a traceback."""


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
    audio: bool = False
    consumes: dict[str, str] = field(default_factory=dict)
    optional_consumes: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    require: tuple[RequireRule, ...] = ()
    folder: str | None = None  # clone folder name; default <name>_microservice
    host_var: str = "SERVICE_HOST"  # env var the service reads its bind address from
    port_var: str = "SERVICE_PORT"  # env var the service reads its port from

    @property
    def repo_dir(self) -> str:
        return self.folder or f"{self.name}_microservice"


@dataclass(frozen=True)
class Registry:
    services: dict[str, ServiceSpec]
    libraries: dict[str, dict[str, str]]
    base_dir: Path


@dataclass(frozen=True)
class ServiceInstance:
    """One service as configured for one machine."""

    spec: ServiceSpec
    branch: str
    runtime: str
    port: int
    env: dict[str, str]


@dataclass(frozen=True)
class Host:
    name: str
    os_family: str  # "windows" | "linux"
    is_raspberry: bool
    workdir: Path
    bind: str
    python: str | None
    secrets: Path | None
    services: dict[str, ServiceInstance]
    remote: dict[str, str]
    source: Path
    base_dir: Path

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


# --------------------------------------------------------------------------- detection


def detect_os() -> tuple[str, bool]:
    """``(os family, is a Raspberry Pi)``."""
    system = platform.system().lower()
    if system == "windows":
        return "windows", False
    raspberry = False
    try:
        raspberry = "raspberry" in Path("/proc/device-tree/model").read_text(errors="ignore").lower()
    except OSError:
        raspberry = platform.machine().lower() in {"armv6l", "armv7l", "aarch64"} and system == "linux"
    return "linux", raspberry


# --------------------------------------------------------------------------- loading


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as error:
        raise DeployError(f"file not found: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise DeployError(f"{path}: invalid TOML: {error}") from error


def load_registry(path: Path) -> Registry:
    data = _read_toml(path)
    services: dict[str, ServiceSpec] = {}
    for name, raw in data.get("services", {}).items():
        try:
            services[name] = ServiceSpec(
                name=name,
                git=raw["git"],
                branch=raw.get("branch", "main"),
                port=int(raw["port"]),
                health=raw.get("health", "/health"),
                ready=raw.get("ready"),
                entry=raw.get("entry", "main.py"),
                requirements=dict(raw.get("requirements", {})),
                libraries=tuple(raw.get("libraries", ())),
                apt=tuple(raw.get("apt", ())),
                audio=bool(raw.get("audio", False)),
                consumes=dict(raw.get("consumes", {})),
                optional_consumes=tuple(raw.get("optional_consumes", ())),
                env={k: str(v) for k, v in raw.get("env", {}).items()},
                require=tuple(
                    RequireRule(r["key"], {k: str(v) for k, v in r.get("when", {}).items()})
                    for r in raw.get("require", ())
                ),
                folder=raw.get("folder"),
                host_var=raw.get("host_var", "SERVICE_HOST"),
                port_var=raw.get("port_var", "SERVICE_PORT"),
            )
        except KeyError as error:
            raise DeployError(f"{path}: service {name!r} is missing {error}") from error
    return Registry(services, dict(data.get("libraries", {})), path.resolve().parent)


def resolve_host_path(host_ref: str, base_dir: Path) -> Path:
    """``--host`` is a path to a TOML file, or the name of ``hosts/<name>.toml``."""
    candidate = Path(host_ref)
    if candidate.suffix == ".toml" or candidate.exists():
        return candidate.resolve()
    return (base_dir / "hosts" / f"{host_ref}.toml").resolve()


def load_host(host_ref: str, registry: Registry) -> Host:
    path = resolve_host_path(host_ref, registry.base_dir)
    data = _read_toml(path)
    section = data.get("host", {})
    detected_os, detected_pi = detect_os()
    declared = section.get("os", "auto")
    if declared not in ("auto", "windows", "linux", "raspberry"):
        raise DeployError(f"{path}: host.os must be auto, windows, linux or raspberry")
    os_family = detected_os if declared == "auto" else ("linux" if declared == "raspberry" else declared)
    is_pi = detected_pi if declared == "auto" else declared == "raspberry"

    workdir = Path(section.get("workdir", "~/oblivion")).expanduser()
    if not workdir.is_absolute():
        workdir = (path.parent / workdir).resolve()
    secrets = section.get("secrets")
    secrets_path = None
    if secrets:
        secrets_path = Path(secrets).expanduser()
        if not secrets_path.is_absolute():
            secrets_path = (registry.base_dir / secrets_path).resolve()

    default_branch = data.get("defaults", {}).get("branch") or None
    instances: dict[str, ServiceInstance] = {}
    for name, raw in data.get("services", {}).items():
        spec = registry.services.get(name)
        if spec is None:
            raise DeployError(f"{path}: unknown service {name!r} (known: {', '.join(sorted(registry.services))})")
        if raw.get("git"):  # e.g. a local checkout: deploy exactly what is committed there
            spec = replace(spec, git=str(raw["git"]))
        instances[name] = ServiceInstance(
            spec=spec,
            branch=raw.get("branch") or default_branch or spec.branch,
            runtime=raw.get("runtime", "native"),
            port=int(raw.get("port", spec.port)),
            env={k: str(v) for k, v in raw.get("env", {}).items()},
        )
    return Host(
        name=section.get("name", path.stem),
        os_family=os_family,
        is_raspberry=is_pi,
        workdir=workdir,
        bind=section.get("bind", "127.0.0.1"),
        python=section.get("python") or None,
        secrets=secrets_path,
        services=instances,
        remote={k: str(v).rstrip("/") for k, v in data.get("remote", {}).items()},
        source=path,
        base_dir=registry.base_dir,
    )


def apply_branch_overrides(host: Host, overrides: list[str]) -> Host:
    """``--branch X`` (every service) or ``--branch svc=X`` (one service), repeatable."""
    if not overrides:
        return host
    services = dict(host.services)
    for item in overrides:
        name, sep, ref = item.partition("=")
        if not sep:
            ref, targets = item, list(services)
        else:
            if name not in services:
                raise DeployError(f"--branch {item}: {name!r} is not deployed on host {host.name!r}")
            targets = [name]
        for target in targets:
            instance = services[target]
            services[target] = ServiceInstance(instance.spec, ref, instance.runtime, instance.port, instance.env)
    return Host(**{**host.__dict__, "services": services})


# --------------------------------------------------------------------------- validation


def validate_host(host: Host) -> tuple[list[str], list[str]]:
    """``(errors, warnings)`` that need no network or clone."""
    errors: list[str] = []
    warnings: list[str] = []
    ports: dict[int, str] = {}
    for name, instance in host.services.items():
        if instance.runtime not in RUNTIMES:
            errors.append(f"{name}: runtime must be one of {RUNTIMES}, not {instance.runtime!r}")
        if instance.runtime == "docker" and instance.spec.audio and host.os_family == "windows":
            errors.append(f"{name}: needs a sound device, which Docker cannot reach on Windows; use runtime = \"native\"")
        if instance.port in ports:
            errors.append(f"{name} and {ports[instance.port]} both use port {instance.port}")
        ports[instance.port] = name
        for target in instance.spec.consumes:
            if target in host.services or target in host.remote:
                continue
            if target in instance.spec.optional_consumes:
                warnings.append(f"{name}: optional service {target!r} is neither local nor in [remote]; it will not be configured")
            else:
                errors.append(f"{name} needs {target!r}: add it to [services] (this machine) or to [remote] (another machine)")
    for target in host.remote:
        if target in host.services:
            warnings.append(f"{target!r} is both local and in [remote]; the local one is used")
    if not host.services:
        errors.append("the host file lists no [services.*]")
    if host.bind == "0.0.0.0":
        warnings.append("bind = 0.0.0.0 exposes the services on every network interface and they have no authentication")
    return errors, warnings
