"""Registry (what the services are) and host files (what runs on one machine)."""

from __future__ import annotations

import platform
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
    prepare: tuple[str, ...] = ()  # script (and its arguments) run with the service's python once its .env is written
    audio: bool = False
    consumes: dict[str, str] = field(default_factory=dict)
    optional_consumes: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    require: tuple[RequireRule, ...] = ()
    folder: str | None = None  # clone folder name; default <name>_microservice
    host_var: str = "SERVICE_HOST"  # env var the service reads its bind address from
    port_var: str = "SERVICE_PORT"  # env var the service reads its port from
    min_python: tuple[int, int] | None = None  # oldest Python the service's pinned dependencies install on
    require_any: tuple[str, ...] = ()  # at least one of these should be set, or the service cannot work
    extra_env: tuple[str, ...] = ()  # variables its code reads that no .env.example lists (glob patterns)
    internal: tuple[str, ...] = ()  # wiring constants and development switches nobody sets on a deployed machine (globs)
    dotenv: bool = True  # the service reads the .env in its own folder; False: service_runner.py reads it for it

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
    env_file: Path | None  # the machine env file: every setting and key of the services on this machine
    services: dict[str, ServiceInstance]
    remote: dict[str, str]
    source: Path
    base_dir: Path
    ref: str = ""  # what --host said: how to name this host again (autostart)
    machine: str | None = None  # the machine of the robot file this host is, when there is one
    topology: Path | None = None  # the robot file (kept under its first name: it is the layout)
    config_all: dict[str, str] = field(default_factory=dict)  # robot.toml [env]: one value for every service that uses it
    config: dict[str, dict[str, str]] = field(default_factory=dict)  # robot.toml [env.<service>] of this machine's services

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
    # The board says so itself. The CPU architecture alone proves nothing: an ARM server is not a Raspberry Pi
    # (it has no GPIO), and a wrong guess picks the wrong requirements file.
    for source in ("/proc/device-tree/model", "/proc/cpuinfo"):
        try:
            if "raspberry pi" in Path(source).read_text(errors="ignore").lower():
                return "linux", True
        except OSError:
            continue
    return "linux", False


# --------------------------------------------------------------------------- topology


@dataclass(frozen=True)
class Machine:
    name: str
    address: str
    services: tuple[str, ...]
    ports: dict[str, int] = field(default_factory=dict)  # only where a service does not use the catalogue's port


@dataclass(frozen=True)
class Topology:
    """The whole robot, once: which machine runs which services, where each machine is, and every setting and key."""

    machines: dict[str, Machine]
    source: Path
    env_all: dict[str, str] = field(default_factory=dict)  # [env] NAME = value: for every service that uses NAME
    env: dict[str, dict[str, str]] = field(default_factory=dict)  # [env.<service>] NAME = value

    def machine_of(self, service: str) -> Machine | None:
        return next((m for m in self.machines.values() if service in m.services), None)


ROBOT_FILE = "robot.toml"  # the single file of truth: layout, settings and keys


def _scalar(value: object, where: str) -> str:
    """A TOML value as the text of an environment variable: ``true`` -> ``true``, ``15`` -> ``15``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise DeployError(f"{where}: must be a string, a number or true/false, not {type(value).__name__}")


def _load_env_tables(path: Path, data: dict[str, Any], registry: "Registry") -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """``[env]`` (scalars: for every service that uses the variable) and ``[env.<service>]`` (one service's own)."""
    shared: dict[str, str] = {}
    per_service: dict[str, dict[str, str]] = {}
    for key, value in data.get("env", {}).items():
        if isinstance(value, dict):
            if key not in registry.services:
                raise DeployError(f"{path}: [env.{key}] is not a service of the catalogue (known: {', '.join(sorted(registry.services))})")
            per_service[key] = {str(k): _scalar(v, f"{path}: [env.{key}] {k}") for k, v in value.items()}
        else:
            shared[str(key)] = _scalar(value, f"{path}: [env] {key}")
    return shared, per_service


def load_topology(path: Path, registry: "Registry") -> Topology | None:
    """The topology file, or None when there is none. Mistakes in it stop everything with a clear message."""
    if not path.exists():
        return None
    data = _read_toml(path)
    machines: dict[str, Machine] = {}
    placed: dict[str, str] = {}
    for name, raw in data.get("machines", {}).items():
        address = str(raw.get("address", "")).strip()
        ipv6 = address.count(":") >= 2  # fe80::1 or [fe80::1]
        if not address or "://" in address or "/" in address or any(c.isspace() for c in address) or (":" in address and not ipv6):
            raise DeployError(f"{path}: machine {name!r} needs address = \"<ip or host name>\" (no http://, no port: ports come from services.toml)")
        services = tuple(raw.get("services", ()))
        for service in services:
            if service not in registry.services:
                raise DeployError(f"{path}: machine {name!r} lists unknown service {service!r} (known: {', '.join(sorted(registry.services))})")
            if service in placed:
                raise DeployError(f"{path}: {service!r} is placed on both {placed[service]!r} and {name!r}; a service runs on one machine")
            placed[service] = name
        ports = {str(k): int(v) for k, v in raw.get("ports", {}).items()}
        for service in ports:
            if service not in services:
                raise DeployError(f"{path}: machine {name!r} sets a port for {service!r}, which it does not run")
        machines[name] = Machine(name, address, services, ports)
    if not machines:
        raise DeployError(f"{path}: no [machines.<name>] tables (see robot.example.toml)")
    env_all, env = _load_env_tables(path, data, registry)
    return Topology(machines, path.resolve(), env_all, env)


def _url_host(address: str) -> str:
    """The address as it is written in a URL: an IPv6 address needs brackets."""
    return f"[{address.strip('[]')}]" if address.count(":") >= 2 else address


def _service_port(topology: Topology, registry: "Registry", service: str) -> int:
    machine = topology.machine_of(service)
    return machine.ports.get(service, registry.services[service].port) if machine else registry.services[service].port


def exposed_services(topology: Topology, registry: "Registry", machine: Machine) -> list[str]:
    """The services of ``machine`` that a service on ANOTHER machine consumes: they must be reachable over the network."""
    return sorted({
        target
        for other in topology.machines.values() if other.name != machine.name
        for service in other.services
        for target in registry.services[service].consumes
        if target in machine.services
    })


def normalise_remote(name: str, value: str, registry: "Registry") -> str:
    """A ``[remote]`` entry as a URL: a bare address gets ``http://`` and the catalogue's port for that service."""
    text = str(value).strip().rstrip("/")
    if "://" in text:
        return text
    if ":" not in text.rpartition("]")[2] and name in registry.services:  # no port given
        text = f"{text}:{registry.services[name].port}"
    return f"http://{text}"


# --------------------------------------------------------------------------- loading


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as error:
        raise DeployError(f"file not found: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise DeployError(f"{path}: invalid TOML: {error}") from error


def _version(text: str) -> tuple[int, int]:
    major, _, minor = str(text).partition(".")
    return int(major), int(minor or 0)


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
                prepare=tuple(raw.get("prepare", ())),
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
                min_python=_version(raw["min_python"]) if "min_python" in raw else None,
                require_any=tuple(raw.get("require_any", ())),
                dotenv=bool(raw.get("dotenv", True)),
                extra_env=tuple(raw.get("extra_env", ())),
                internal=tuple(raw.get("internal", ())),
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


def load_host(host_ref: str, registry: Registry, topology_file: Path | None = None, *, from_topology: bool = False) -> Host:
    """A host from ``hosts/<name>.toml``, or, with no such file, from the machine of that name in the topology.

    A host that names its machine (``[host] machine``, or implicitly by having no file) is derived from the topology:
    its services, the URLs of the services on the other machines and its bind address need not be written anywhere.
    """
    path = resolve_host_path(host_ref, registry.base_dir)
    topology = load_topology(topology_file or registry.base_dir / ROBOT_FILE, registry)
    if topology is not None and host_ref in topology.machines and (from_topology or not path.exists()):
        data: dict[str, Any] = {"host": {"machine": host_ref}}
        source = topology.source
    else:
        data = _read_toml(path)
        source = path
    section = data.get("host", {})
    machine_name = section.get("machine")
    machine: Machine | None = None
    if machine_name:
        if topology is None:
            raise DeployError(f"{path}: host.machine = {machine_name!r} but there is no {ROBOT_FILE} (copy robot.example.toml)")
        if machine_name not in topology.machines:
            raise DeployError(f"{path}: machine {machine_name!r} is not in {topology.source.name} (has: {', '.join(topology.machines)})")
        machine = topology.machines[machine_name]

    detected_os, detected_pi = detect_os()
    declared = section.get("os", "auto")
    if declared not in ("auto", "windows", "linux", "raspberry"):
        raise DeployError(f"{path}: host.os must be auto, windows, linux or raspberry")
    os_family = detected_os if declared == "auto" else ("linux" if declared == "raspberry" else declared)
    is_pi = detected_pi if declared == "auto" else declared == "raspberry"

    workdir = Path(section.get("workdir", "~/oblivion")).expanduser()
    if not workdir.is_absolute():
        workdir = (source.parent / workdir).resolve()
    declared_file = section.get("env_file") or section.get("secrets")  # "secrets" is the older name of the same key
    env_file_path = None
    if declared_file:
        env_file_path = Path(declared_file).expanduser()
        if not env_file_path.is_absolute():
            env_file_path = (registry.base_dir / env_file_path).resolve()
    elif machine is not None:  # by convention secrets/<machine>.env; a machine that needs none simply has no file
        conventional = registry.base_dir / "secrets" / f"{machine.name}.env"
        env_file_path = conventional if conventional.exists() else None

    default_branch = data.get("defaults", {}).get("branch") or None
    raw_services: dict[str, Any] = data.get("services", {})
    if machine is not None:
        stray = [n for n in raw_services if n not in machine.services]
        if stray:
            where = topology.machine_of(stray[0]) if topology else None
            raise DeployError(
                f"{path}: [services.{stray[0]}] is not one of the services of machine {machine.name!r} in {topology.source.name}"
                + (f" (it runs on {where.name!r})" if where else " (it is placed nowhere)")
            )
    instances: dict[str, ServiceInstance] = {}
    for name in [*(machine.services if machine else ()), *(n for n in raw_services if machine is None)]:
        spec = registry.services.get(name)
        if spec is None:
            raise DeployError(f"{path}: unknown service {name!r} (known: {', '.join(sorted(registry.services))})")
        raw = raw_services.get(name, {})
        if raw.get("git"):  # e.g. a local checkout: deploy exactly what is committed there
            spec = replace(spec, git=str(raw["git"]))
        catalogue_port = machine.ports.get(name, spec.port) if machine else spec.port
        instances[name] = ServiceInstance(
            spec=spec,
            branch=raw.get("branch") or default_branch or spec.branch,
            runtime=raw.get("runtime", "native"),
            port=int(raw.get("port", catalogue_port)),
            env={k: str(v) for k, v in raw.get("env", {}).items()},
        )

    remote: dict[str, str] = {}
    bind = section.get("bind", "127.0.0.1")
    if machine is not None and topology is not None:
        for other in topology.machines.values():
            if other.name == machine.name:
                continue
            for service in other.services:
                remote[service] = f"http://{_url_host(other.address)}:{_service_port(topology, registry, service)}"
        if "bind" not in section:  # reachable only if another machine calls one of our services
            bind = "0.0.0.0" if exposed_services(topology, registry, machine) else "127.0.0.1"
    for name, value in data.get("remote", {}).items():  # written by hand: wins over the derived one
        remote[name] = normalise_remote(name, str(value), registry)

    return Host(
        name=section.get("name", machine.name if machine else path.stem),
        os_family=os_family,
        is_raspberry=is_pi,
        workdir=workdir,
        bind=bind,
        python=section.get("python") or None,
        env_file=env_file_path,
        services=instances,
        remote=remote,
        source=source,
        base_dir=registry.base_dir,
        ref=host_ref if machine is not None and (from_topology or not path.exists()) else str(path),
        machine=machine.name if machine else None,
        topology=topology.source if topology and machine else None,
        config_all=dict(topology.env_all) if topology and machine else {},
        config={n: dict(v) for n, v in topology.env.items() if machine and n in machine.services} if topology and machine else {},
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
                where = "add it to a machine of the topology" if host.machine else "add it to [services] (this machine) or to [remote] (another machine)"
                errors.append(f"{name} needs {target!r}: {where}")
    for target, url in host.remote.items():
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or any(c.isspace() for c in url):
            errors.append(f"[remote] {target}: {url!r} is not an address like 192.168.1.20, 192.168.1.20:8000 or http://192.168.1.20:8000")
        elif parsed.hostname in ("localhost", "127.0.0.1", "::1"):
            warnings.append(f"[remote] {target}: {url} points at this machine; a service on another machine needs its own address")
        if target in host.services:
            warnings.append(f"{target!r} is both local and in [remote]; the local one is used")
    if not host.services:
        errors.append("the host file lists no [services.*]")
    if host.bind == "0.0.0.0":
        warnings.append("bind = 0.0.0.0 exposes the services on every network interface and they have no authentication")
    return errors, warnings
