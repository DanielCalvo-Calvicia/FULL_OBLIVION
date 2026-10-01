"""``oblivion compat``: do the services, each on the branch, tag or commit it will be deployed from, fit together?

Two kinds of check, neither changes anything:

* **remote** (``--remote``, needs the network): the branch, tag or commit of every service exists on its git remote.
* **workspace** (offline, needs the development workspace next to this repository): for every service folder, its
  bundled ``contracts`` wheel is the same version in every service and equals the ``contracts`` source, its requirements
  files install that wheel, its ``.env.example`` port is the catalogue's, and its local checkout is on the ref the tool
  will deploy and has everything pushed (a deploy takes the code from the remote, not from the working copy).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import gitops
from .config import SERVICES_DIR, Registry, ServiceFile, ServiceSpec, load_service_files
from .shell import Shell

ERROR, WARNING, OK = "error", "warning", "ok"
_WHEEL = re.compile(r"^contracts_microservice-(?P<version>[0-9][^-]*)-py3-none-any\.whl$")
_PORT_NAMES = ("SERVICE_PORT", "AI_AGENT_PORT")


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning" | "ok"
    service: str  # a service name, or "contracts" / "all"
    message: str


def resolved_ref(spec: ServiceSpec, files: dict[str, ServiceFile]) -> tuple[str, str]:
    """``(ref, where it comes from)`` for a service deployed without a host file or ``--branch``."""
    file = files.get(spec.name)
    if file is not None and file.ref:
        return file.ref, f"{SERVICES_DIR}/{spec.name}.toml ({file.ref_kind})"
    return spec.branch, "services.toml"


def _contracts_source_version(workspace: Path) -> str | None:
    pyproject = workspace / "contracts" / "pyproject.toml"
    if not pyproject.exists():
        return None
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
    return match.group(1) if match else None


def _wheels(folder: Path) -> list[str]:
    vendor = folder / "vendor"
    return sorted(p.name for p in vendor.glob("contracts_microservice-*.whl")) if vendor.is_dir() else []


def _env_example_port(folder: Path) -> int | None:
    example = folder / ".env.example"
    if not example.exists():
        return None
    for line in example.read_text(encoding="utf-8", errors="ignore").splitlines():
        name, _, value = line.partition("=")
        if name.strip() in _PORT_NAMES and value.strip().split("#")[0].strip().isdigit():
            return int(value.strip().split("#")[0].strip())
    return None


def check_workspace(registry: Registry, files: dict[str, ServiceFile], workspace: Path, shell: Shell, names: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    source_version = _contracts_source_version(workspace)
    if source_version is None:
        findings.append(Finding(WARNING, "contracts", f"no contracts source at {workspace / 'contracts'}: the bundled wheels cannot be compared with it"))
    versions: dict[str, str] = {}

    for name in names:
        spec = registry.services[name]
        folder = workspace / spec.repo_dir
        if not folder.is_dir():
            findings.append(Finding(WARNING, name, f"no checkout at {folder}: workspace checks skipped"))
            continue

        wheels = _wheels(folder)
        if len(wheels) != 1:
            findings.append(Finding(ERROR, name, f"vendor/ must hold exactly one contracts wheel, found {wheels or 'none'}"))
        else:
            version = _WHEEL.match(wheels[0])
            versions[name] = version.group("version") if version else wheels[0]
            for relative in spec.requirements.values():
                requirements = folder / relative
                if requirements.exists() and f"./vendor/{wheels[0]}" not in requirements.read_text(encoding="utf-8", errors="ignore"):
                    findings.append(Finding(ERROR, name, f"{relative} does not install ./vendor/{wheels[0]}"))
        port = _env_example_port(folder)
        if port is not None and port != spec.port:
            findings.append(Finding(ERROR, name, f".env.example says port {port} but services.toml says {spec.port}"))

        ref, where = resolved_ref(spec, files)
        branch = gitops.current_branch(shell, folder)
        if branch is None:
            findings.append(Finding(WARNING, name, "the checkout is not a git repository: branch and push state not checked"))
            continue
        if branch != ref:
            findings.append(Finding(WARNING, name, f"checked out on {branch!r}, but it will be deployed from {ref!r} ({where})"))
        status = shell.run(["git", "-C", folder, "status", "-sb"], check=False, capture=True, mutating=False).stdout.splitlines()
        header = status[0] if status else ""
        ahead = re.search(r"ahead (\d+)", header)
        behind = re.search(r"behind (\d+)", header)
        if ahead:
            findings.append(Finding(WARNING, name, f"{ahead.group(1)} commit(s) not pushed: a deploy from the remote will not have them"))
        if behind:
            findings.append(Finding(WARNING, name, f"{behind.group(1)} commit(s) behind its remote branch"))

    if versions:
        distinct = sorted(set(versions.values()))
        if len(distinct) > 1:
            findings.append(Finding(ERROR, "contracts", "services bundle different contracts versions: " + ", ".join(f"{s}={v}" for s, v in sorted(versions.items()))))
        elif source_version and distinct[0] != source_version:
            findings.append(Finding(ERROR, "contracts", f"services bundle contracts {distinct[0]} but the source is {source_version}: run contracts/scripts/bundle.py"))
        else:
            findings.append(Finding(OK, "contracts", f"every checked service bundles contracts {distinct[0]}"))
    return findings


def check_remote(registry: Registry, files: dict[str, ServiceFile], shell: Shell, names: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for name in names:
        spec = registry.services[name]
        ref, where = resolved_ref(spec, files)
        result = shell.run(["git", "ls-remote", "--heads", "--tags", spec.git, ref, f"{ref}^{{}}"], check=False, capture=True, mutating=False)
        if result.returncode != 0:
            findings.append(Finding(ERROR, name, f"cannot reach {spec.git}: {(result.stderr or '').strip()[-200:]}"))
        elif result.stdout.strip():
            findings.append(Finding(OK, name, f"{ref!r} exists on the remote ({where})"))
        elif re.fullmatch(r"[0-9a-f]{7,40}", ref):
            findings.append(Finding(WARNING, name, f"{ref!r} looks like a commit: ls-remote cannot confirm it (it is fetched at deploy)"))
        else:
            findings.append(Finding(ERROR, name, f"{ref!r} is not a branch or tag of {spec.git} ({where})"))
    return findings


def run_compat(
    registry: Registry, shell: Shell, workspace: Path, *, remote: bool, names: list[str] | None = None
) -> list[Finding]:
    files = load_service_files(registry.base_dir, registry)
    selected = names or list(registry.services)
    findings: list[Finding] = []
    for name, spec in ((n, registry.services[n]) for n in selected):
        ref, where = resolved_ref(spec, files)
        findings.append(Finding(OK, name, f"deployed from {ref!r} ({where})"))
    findings += check_workspace(registry, files, workspace, shell, selected)
    if remote:
        findings += check_remote(registry, files, shell, selected)
    return findings
