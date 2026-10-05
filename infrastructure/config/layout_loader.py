"""Which layout is in use (``config/robot.toml``) and what it says (``config/layouts/<name>.toml``)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from domain.entities.catalogue import Catalogue
from domain.entities.layout import Layout, Machine
from domain.errors import DeployError
from infrastructure.config.paths import ConfigPaths
from infrastructure.config.toml_reader import check_keys, read_toml

_LAYOUT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class RobotFile:
    """``config/robot.toml``: the only file every robot needs. Which layout, and where each machine is."""

    layout: str
    addresses: dict[str, str]
    source: Path


def available_layouts(paths: ConfigPaths) -> list[str]:
    return sorted(p.stem for p in paths.layouts.glob("*.toml")) if paths.layouts.is_dir() else []


def read_robot_file(paths: ConfigPaths) -> RobotFile:
    path = paths.robot
    if not path.exists():
        raise DeployError(
            f"no {paths.label(path)}: copy config/robot.example.toml to config/robot.toml and fill it in "
            f"(or run  python oblivion.py init --layout <name>;  layouts: {', '.join(available_layouts(paths)) or 'none'})"
        )
    data = read_toml(path)
    check_keys(path, data, {"layout", "addresses"}, "allowed: layout = \"<name>\" and an [addresses] table")
    layout = str(data.get("layout", "")).strip()
    if not layout:
        raise DeployError(f"{path}: layout = \"<name>\" is missing (one of: {', '.join(available_layouts(paths)) or 'none'})")
    addresses = data.get("addresses", {})
    if not isinstance(addresses, dict):
        raise DeployError(f"{path}: [addresses] must be a table of  machine = \"<ip or host name>\"")
    return RobotFile(layout, {str(k): str(v).strip() for k, v in addresses.items()}, path.resolve())


def _check_address(path: Path, machine: str, address: str) -> None:
    ipv6 = address.count(":") >= 2  # fe80::1 or [fe80::1]
    if not address or "://" in address or "/" in address or any(c.isspace() for c in address) or (":" in address and not ipv6):
        raise DeployError(
            f"{path}: the address of machine {machine!r} must be an IP or a host name, "
            f"not {address!r} (no http://, no port: ports come from config/catalogue.toml)"
        )


def _read_layout_file(paths: ConfigPaths, name: str) -> tuple[Path, dict[str, Any]]:
    if not _LAYOUT_NAME.match(name):
        raise DeployError(f"layout {name!r} is not a valid name (letters, digits, '.', '-', '_')")
    path = paths.layout_file(name)
    if not path.exists():
        raise DeployError(
            f"layout {name!r} not found: there is no {paths.label(path)} "
            f"(available: {', '.join(available_layouts(paths)) or 'none'})"
        )
    return path, read_toml(path)


def load_layout(paths: ConfigPaths, catalogue: Catalogue, robot: RobotFile | None = None) -> Layout:
    """The layout chosen in robot.toml, with every machine's address filled in. Mistakes stop everything with a clear message."""
    robot = robot or read_robot_file(paths)
    path, data = _read_layout_file(paths, robot.layout)
    check_keys(path, data, {"description", "machines"}, "allowed: description and [machines.<name>] tables")
    machines: dict[str, Machine] = {}
    placed: dict[str, str] = {}
    for name, raw in data.get("machines", {}).items():
        check_keys(path, raw, {"address", "services", "ports"}, f"machine {name!r}: allowed address, services, ports")
        address = str(robot.addresses.get(name) or raw.get("address", "")).strip()
        if not address:
            raise DeployError(
                f"machine {name!r} of layout {robot.layout!r} has no address: add  {name} = \"<ip or host name>\"  "
                f"under [addresses] in {paths.label(robot.source)}"
            )
        _check_address(robot.source if name in robot.addresses else path, name, address)
        services = tuple(raw.get("services", ()))
        for service in services:
            if service not in catalogue.services:
                raise DeployError(f"{path}: machine {name!r} lists unknown service {service!r} (known: {', '.join(sorted(catalogue.services))})")
            if service in placed:
                raise DeployError(f"{path}: {service!r} is placed on both {placed[service]!r} and {name!r}; a service runs on one machine")
            placed[service] = name
        ports = {str(k): int(v) for k, v in raw.get("ports", {}).items()}
        for service in ports:
            if service not in services:
                raise DeployError(f"{path}: machine {name!r} sets a port for {service!r}, which it does not run")
        machines[name] = Machine(name, address, services, ports)
    if not machines:
        raise DeployError(f"{path}: no [machines.<name>] tables")
    stray = sorted(set(robot.addresses) - set(machines))
    if stray:
        raise DeployError(
            f"{robot.source}: [addresses] names {', '.join(stray)}, which layout {robot.layout!r} does not have "
            f"(machines: {', '.join(machines)})"
        )
    return Layout(robot.layout, machines, path.resolve(), str(data.get("description", "")).strip())


def describe_layouts(paths: ConfigPaths) -> list[tuple[str, str, dict[str, list[str]]]]:
    """``(name, description, {machine: [services]})`` of every layout file, for ``oblivion layouts``. Reads nothing else."""
    result = []
    for name in available_layouts(paths):
        data = read_toml(paths.layout_file(name))
        machines = {m: list(raw.get("services", ())) for m, raw in data.get("machines", {}).items()}
        result.append((name, str(data.get("description", "")).strip(), machines))
    return result


def write_robot_file(paths: ConfigPaths, layout: str, addresses: dict[str, str], *, overwrite: bool = False) -> Path:
    """Create ``config/robot.toml`` (``oblivion init``). Refuses to replace an existing file unless ``overwrite``."""
    path = paths.robot
    if path.exists() and not overwrite:
        raise DeployError(f"{paths.label(path)} already exists: edit it, or pass --force to replace it")
    lines = [
        "# Which layout this robot uses, and where each of its machines is. Layouts: config/layouts/",
        f'layout = "{layout}"',
        "",
        "[addresses]   # an IP or a host name (no http://, no port). The layout names the machines.",
    ]
    lines += [f'{machine} = "{address}"' for machine, address in addresses.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
