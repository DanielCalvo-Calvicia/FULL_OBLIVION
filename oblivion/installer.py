"""Turning a fetched service repo into a runnable installation (virtualenv + dependencies)."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from .config import DeployError, Host, Registry, ServiceSpec
from .shell import Shell

_PATH_ESCAPE = re.compile(r"^\s*(-e|--editable)\s+\.\.[/\\]")


def requirements_file(host: Host, spec: ServiceSpec, service_dir: Path) -> tuple[Path | None, str | None]:
    """The requirements file for this OS and a warning when the other OS's file had to be used."""
    wanted = spec.requirements.get(host.os_family)
    other_family = "linux" if host.os_family == "windows" else "windows"
    if wanted and (service_dir / wanted).exists():
        return service_dir / wanted, None
    fallback = spec.requirements.get(other_family)
    if fallback and (service_dir / fallback).exists():
        return service_dir / fallback, (
            f"{spec.name}: no requirements file for {host.os_family}; using {fallback}. "
            "Check that every dependency has a build for this OS"
        )
    if not service_dir.exists():  # dry run before the first clone: nothing to look at yet
        return None, None
    return None, f"{spec.name}: no requirements file found in {service_dir}"


def filtered_requirements(path: Path) -> str:
    """The file without ``-e ../<sibling>`` lines: independent repos have no siblings.

    Shared libraries are installed from their configured source instead (see services.toml).
    """
    kept = [line for line in path.read_text(encoding="utf-8").splitlines() if not _PATH_ESCAPE.match(line)]
    return "\n".join(kept) + "\n"


def library_pip_args(registry: Registry, library: str) -> list[str]:
    source = registry.libraries.get(library)
    if not source:
        raise DeployError(f"library {library!r} is not defined in services.toml [libraries]")
    if "path" in source:
        path = Path(source["path"]).expanduser()
        path = path if path.is_absolute() else (registry.base_dir / path).resolve()
        if not path.exists():
            raise DeployError(
                f"library {library!r}: {path} does not exist. Set [libraries.{library}] git or wheel_dir "
                "in services.toml for machines that do not have the workspace"
            )
        return [str(path)]
    if "git" in source:
        return [f"git+{source['git']}"]
    if "wheel_dir" in source:
        return ["--no-index", "--find-links", str(Path(source["wheel_dir"]).expanduser()), library]
    raise DeployError(f"library {library!r}: give path, git or wheel_dir")


def _library_stamp(registry: Registry, library: str) -> str:
    source = registry.libraries.get(library, {})
    if "path" in source:
        root = Path(library_pip_args(registry, library)[0])
        files = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
        return json.dumps([[str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns] for p in files])
    return json.dumps(source, sort_keys=True)


def fingerprint(host: Host, registry: Registry, name: str, requirements: Path | None) -> str:
    spec = host.services[name].spec
    service_dir = host.service_dir(name)
    digest = hashlib.sha256()
    digest.update(sys.version.encode() if host.python is None else host.python.encode())
    if requirements is not None:
        digest.update(filtered_requirements(requirements).encode())
    for wheel in sorted((service_dir / "vendor").glob("*.whl")):
        digest.update(f"{wheel.name}:{wheel.stat().st_size}".encode())
    for library in spec.libraries:
        digest.update(_library_stamp(registry, library).encode())
    return digest.hexdigest()


def install_native(
    shell: Shell, host: Host, registry: Registry, name: str, *, previous_fingerprint: str | None, system_deps: bool
) -> tuple[str, list[str]]:
    """Create the virtualenv and install dependencies. Returns ``(fingerprint, warnings)``."""
    spec = host.services[name].spec
    service_dir = host.service_dir(name)
    requirements, warning = requirements_file(host, spec, service_dir)
    warnings = [warning] if warning else []

    if system_deps and host.os_family == "linux" and spec.apt:
        shell.run(["sudo", "apt-get", "install", "-y", *spec.apt])
    elif spec.apt and host.os_family == "linux":
        warnings.append(f"{name}: may need system packages: {' '.join(spec.apt)} (re-run with --system-deps to install them)")

    current = fingerprint(host, registry, name, requirements) if not shell.dry_run or service_dir.exists() else "dry-run"
    venv = host.venv_dir(name)
    python = shell.python_of(venv)
    if previous_fingerprint == current and python.exists():
        shell.say(f"{name}: dependencies unchanged, skipping install")
        return current, warnings

    packages = requirements is not None and any(
        line.strip() and not line.strip().startswith("#") for line in filtered_requirements(requirements).splitlines()
    )
    needs_pip = packages or bool(spec.libraries)
    if not python.exists():
        if not shell.dry_run:
            venv.parent.mkdir(parents=True, exist_ok=True)
        shell.run([host.python or sys.executable, "-m", "venv", *([] if needs_pip else ["--without-pip"]), venv])
    if needs_pip and not shell.dry_run and shell.run([python, "-m", "pip", "--version"], check=False, capture=True, mutating=False).returncode != 0:
        shell.run([python, "-m", "ensurepip", "--upgrade"])  # a venv created earlier without pip
    if packages:
        filtered = host.state_dir() / f"{name}.requirements.txt"
        if not shell.dry_run:
            filtered.parent.mkdir(parents=True, exist_ok=True)
            filtered.write_text(filtered_requirements(requirements), encoding="utf-8")
        # cwd = the service folder, so "./vendor/<wheel>" lines resolve
        shell.run([python, "-m", "pip", "install", "--quiet", "-r", filtered], cwd=service_dir)
    for library in spec.libraries:
        shell.run([python, "-m", "pip", "install", "--quiet", *library_pip_args(registry, library)], cwd=service_dir)
    return current, warnings
