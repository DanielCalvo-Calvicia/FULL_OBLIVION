"""Adapter of InstallerPort: a fetched service repo becomes a runnable installation (virtualenv + dependencies)."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path

from application.ports.outbound.installer_port import InstallerPort
from application.ports.outbound.shell_port import ShellPort
from domain.entities.catalogue import Catalogue
from domain.entities.host import Host
from domain.entities.service_spec import ServiceSpec
from domain.errors import DeployError
from infrastructure.outbound.runtime import docker_runtime

_PATH_ESCAPE = re.compile(r"^\s*(-e|--editable)\s+\.\.[/\\]")
CATALOGUE_FILE = "config/catalogue.toml"


def requirements_file(host: Host, spec: ServiceSpec, service_dir: Path) -> tuple[Path | None, str | None]:
    """The requirements file for this OS and a warning when the other OS's file had to be used."""
    wanted = (spec.requirements.get("raspberry") if host.is_raspberry else None) or spec.requirements.get(host.os_family)
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

    Shared libraries are installed from their configured source instead (see config/catalogue.toml).
    """
    kept = [line for line in path.read_text(encoding="utf-8").splitlines() if not _PATH_ESCAPE.match(line)]
    return "\n".join(kept) + "\n"


# --------------------------------------------------------------------------- shared libraries


def _resolve(catalogue: Catalogue, value: str) -> Path:
    """A configured path: ``~`` expanded, relative ones relative to the repository root (never to the caller's cwd)."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (catalogue.base_dir / path).resolve()


def _library_wheels(library: str, folder: Path) -> list[Path]:
    prefix = library.replace("-", "_").lower() + "-"
    return sorted(p for p in folder.glob("*.whl") if p.name.lower().startswith(prefix)) if folder.is_dir() else []


def bundled_wheels(catalogue: Catalogue, library: str) -> list[Path]:
    """The wheels of a library served from ``wheel_dir``."""
    kind, location = library_source(catalogue, library)
    return _library_wheels(library, Path(location)) if kind == "wheel_dir" else []


def library_source(catalogue: Catalogue, library: str) -> tuple[str, Path | str]:
    """``(kind, location)`` of the first usable source, in the order ``path``, ``wheel_dir``, ``git``.

    ``path`` is the workspace checkout (only usable where it exists); ``wheel_dir`` holds wheels bundled with
    this repository, so a machine without the workspace still gets the library.
    """
    source = catalogue.libraries.get(library)
    if not source:
        raise DeployError(f"library {library!r} is not defined in {CATALOGUE_FILE} [libraries]")
    if "path" in source and _resolve(catalogue, source["path"]).exists():
        return "path", _resolve(catalogue, source["path"])
    if "wheel_dir" in source and _library_wheels(library, _resolve(catalogue, source["wheel_dir"])):
        return "wheel_dir", _resolve(catalogue, source["wheel_dir"])
    if "git" in source:
        return "git", source["git"]
    tried = [f"path {_resolve(catalogue, source['path'])}"] if "path" in source else []
    tried += [f"wheel_dir {_resolve(catalogue, source['wheel_dir'])} (no {library} wheel)"] if "wheel_dir" in source else []
    if not tried:
        raise DeployError(f"library {library!r}: give path, wheel_dir or git in {CATALOGUE_FILE} [libraries]")
    raise DeployError(
        f"library {library!r} is not available on this machine: tried {'; '.join(tried)}. "
        f"Bundle the wheel with scripts/bundle_shared_logging.py or set [libraries.{library}] git in {CATALOGUE_FILE}"
    )


def check_libraries(catalogue: Catalogue, libraries: set[str]) -> tuple[list[str], list[str]]:
    """``(errors, warnings)`` for the libraries the selected services need. No network, nothing installed."""
    errors: list[str] = []
    warnings: list[str] = []
    for library in sorted(libraries):
        try:
            kind, _ = library_source(catalogue, library)
        except DeployError as error:
            errors.append(str(error))
            continue
        source = catalogue.libraries[library]
        if kind == "path" and "wheel_dir" in source:
            stale = _stale_wheel(catalogue, library)
            if stale:
                warnings.append(stale)
    return errors, warnings


def _stale_wheel(catalogue: Catalogue, library: str) -> str | None:
    """A message when the bundled wheel is older than the checkout it was built from (other machines get the wheel)."""
    source = catalogue.libraries[library]
    wheels = _library_wheels(library, _resolve(catalogue, source["wheel_dir"]))
    project = _resolve(catalogue, source["path"]) / "pyproject.toml"
    try:
        with project.open("rb") as handle:
            version = tomllib.load(handle)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return None
    bundled = [w.name.split("-")[1] for w in wheels]
    if version in bundled:
        return None
    return (
        f"library {library}: the checkout is version {version} but the bundled wheel is "
        f"{', '.join(bundled) or 'missing'}; machines without the workspace get the wheel. "
        "Run scripts/bundle_shared_logging.py and commit it"
    )


def library_pip_args(catalogue: Catalogue, library: str) -> list[str]:
    kind, location = library_source(catalogue, library)
    if kind == "path":
        return [str(location)]
    if kind == "wheel_dir":
        # --no-index: a same-named package on PyPI must never win. --force-reinstall: a rebuilt wheel of the
        # same version still replaces the installed one. Dependencies come from the service's own requirements.
        return ["--no-index", "--no-deps", "--force-reinstall", "--find-links", str(location), library]
    return [f"git+{location}"]


def _library_stamp(catalogue: Catalogue, library: str) -> str:
    kind, location = library_source(catalogue, library)
    if kind == "path":
        root = Path(location)
        files = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
        return json.dumps([[str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns] for p in files])
    if kind == "wheel_dir":
        return json.dumps([[w.name, w.stat().st_size, w.stat().st_mtime_ns] for w in _library_wheels(library, Path(location))])
    return json.dumps([kind, location])


def fingerprint(host: Host, catalogue: Catalogue, name: str, requirements: Path | None) -> str:
    spec = host.services[name].spec
    service_dir = host.service_dir(name)
    digest = hashlib.sha256()
    digest.update(sys.version.encode() if host.python is None else host.python.encode())
    if requirements is not None:
        digest.update(filtered_requirements(requirements).encode())
    for wheel in sorted((service_dir / "vendor").glob("*.whl")):
        digest.update(f"{wheel.name}:{wheel.stat().st_size}".encode())
    for library in spec.libraries:
        digest.update(_library_stamp(catalogue, library).encode())
    return digest.hexdigest()


# --------------------------------------------------------------------------- the adapter


class NativeInstaller(InstallerPort):
    def __init__(self, shell: ShellPort) -> None:
        self._shell = shell

    def interpreter_version(self, host: Host) -> tuple[int, int]:
        """Version of the Python that builds the virtualenvs: the machine's ``python``, else the one running this tool."""
        if host.python is None:
            return sys.version_info[0], sys.version_info[1]
        result = self._shell.run(
            [host.python, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            check=False, capture=True, mutating=False,
        )
        try:
            major, minor = result.stdout.split()[:2]
            return int(major), int(minor)
        except ValueError as error:
            raise DeployError(f"cannot run the Python named in config/machines/{host.name}.toml: {host.python}") from error

    def check_python(self, host: Host, selected: list[str]) -> list[str]:
        needing = [n for n in selected if host.services[n].runtime == "native" and host.services[n].spec.min_python]
        if not needing:
            return []
        found = self.interpreter_version(host)
        return [
            f"{name} needs Python {'.'.join(map(str, spec.min_python))}+ but the interpreter for this machine is "
            f"{found[0]}.{found[1]}: install a newer Python and set python = \"<path>\" under [host] in "
            f"config/machines/{host.name}.toml, or run {name} on another machine (config/layouts/)"
            for name in needing
            if (spec := host.services[name].spec) and spec.min_python and found < spec.min_python
        ]

    def check_libraries(self, catalogue: Catalogue, libraries: set[str]) -> tuple[list[str], list[str]]:
        return check_libraries(catalogue, libraries)

    def install_native(
        self, host: Host, catalogue: Catalogue, name: str, *, previous_fingerprint: str | None, system_deps: bool
    ) -> tuple[str, list[str]]:
        """Create the virtualenv and install dependencies. Returns ``(fingerprint, warnings)``."""
        shell = self._shell
        spec = host.services[name].spec
        service_dir = host.service_dir(name)
        requirements, warning = requirements_file(host, spec, service_dir)
        warnings = [warning] if warning else []

        if system_deps and host.os_family == "linux" and spec.apt:
            if not shell.apt_updated:  # a freshly installed machine has empty or stale package lists
                shell.run(["sudo", "apt-get", "update"])
                shell.apt_updated = True
            shell.run(["sudo", "apt-get", "install", "-y", *spec.apt])
        elif spec.apt and host.os_family == "linux":
            warnings.append(f"{name}: may need system packages: {' '.join(spec.apt)} (re-run with --system-deps to install them)")

        current = fingerprint(host, catalogue, name, requirements) if not shell.dry_run or service_dir.exists() else "dry-run"
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
            shell.run([python, "-m", "pip", "install", "--quiet", *library_pip_args(catalogue, library)], cwd=service_dir)
        return current, warnings

    def build_image(self, host: Host, catalogue: Catalogue, name: str) -> None:
        shell = self._shell
        docker_runtime.require_docker()
        spec = host.services[name].spec
        requirements, warning = requirements_file(host, spec, host.service_dir(name))
        if warning:
            shell.say(f"warning: {warning}")
        if requirements is None:
            raise DeployError(f"{name}: no requirements file to build the image from")
        wheels_dir = host.workdir / "build" / f"{name}-wheels"
        if not shell.dry_run:
            wheels_dir.mkdir(parents=True, exist_ok=True)
        for library in spec.libraries:
            kind, _location = library_source(catalogue, library)
            if kind == "wheel_dir":  # already a wheel: no build needed
                for wheel in bundled_wheels(catalogue, library):
                    shell.say(f"copy {wheel.name} -> {wheels_dir}")
                    if not shell.dry_run:
                        shutil.copy2(wheel, wheels_dir / wheel.name)
                continue
            shell.run([
                host.python or sys.executable, "-m", "pip", "wheel", "--quiet", "--no-deps",
                "-w", wheels_dir, *library_pip_args(catalogue, library),
            ])
        wheels = sorted(wheels_dir.glob("*.whl")) if wheels_dir.exists() else []
        context = docker_runtime.prepare_context(shell, host, name, filtered_requirements(requirements), wheels)
        docker_runtime.build(shell, host, name, context)
