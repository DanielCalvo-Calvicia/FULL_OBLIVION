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

from application.ports.outbound.source_control_port import SourceControlPort
from application.ports.outbound.workspace_port import WorkspacePort
from domain.entities.catalogue import Catalogue

ERROR, WARNING, OK = "error", "warning", "ok"
_WHEEL = re.compile(r"^contracts_microservice-(?P<version>[0-9][^-]*)-py3-none-any\.whl$")

Refs = dict[str, tuple[str, str]]  # service -> (the ref it is deployed from, which file says so)


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning" | "ok"
    service: str  # a service name, or "contracts" / "all"
    message: str


class CompatService:
    def __init__(self, catalogue: Catalogue, git: SourceControlPort, workspace_files: WorkspacePort) -> None:
        self._catalogue = catalogue
        self._git = git
        self._files = workspace_files

    def run(self, refs: Refs, workspace: Path, *, remote: bool, names: list[str] | None = None) -> list[Finding]:
        selected = names or list(self._catalogue.services)
        findings = [Finding(OK, name, f"deployed from {refs[name][0]!r} ({refs[name][1]})") for name in selected]
        findings += self._check_workspace(refs, workspace, selected)
        if remote:
            findings += self._check_remote(refs, selected)
        return findings

    def _check_workspace(self, refs: Refs, workspace: Path, names: list[str]) -> list[Finding]:
        findings: list[Finding] = []
        source_version = self._files.contracts_source_version(workspace)
        if source_version is None:
            findings.append(Finding(WARNING, "contracts", f"no contracts source at {workspace / 'contracts'}: the bundled wheels cannot be compared with it"))
        versions: dict[str, str] = {}

        for name in names:
            spec = self._catalogue.services[name]
            folder = workspace / spec.repo_dir
            if not self._files.is_dir(folder):
                findings.append(Finding(WARNING, name, f"no checkout at {folder}: workspace checks skipped"))
                continue

            wheels = self._files.contracts_wheels(folder)
            if len(wheels) != 1:
                findings.append(Finding(ERROR, name, f"vendor/ must hold exactly one contracts wheel, found {wheels or 'none'}"))
            else:
                version = _WHEEL.match(wheels[0])
                versions[name] = version.group("version") if version else wheels[0]
                for relative in spec.requirements.values():
                    text = self._files.requirements_text(folder, relative)
                    if text is not None and f"./vendor/{wheels[0]}" not in text:
                        findings.append(Finding(ERROR, name, f"{relative} does not install ./vendor/{wheels[0]}"))
            port = self._files.env_example_port(folder)
            if port is not None and port != spec.port:
                findings.append(Finding(ERROR, name, f".env.example says port {port} but the catalogue says {spec.port}"))

            ref, where = refs[name]
            branch = self._git.current_branch(folder)
            if branch is None:
                findings.append(Finding(WARNING, name, "the checkout is not a git repository: branch and push state not checked"))
                continue
            if branch != ref:
                findings.append(Finding(WARNING, name, f"checked out on {branch!r}, but it will be deployed from {ref!r} ({where})"))
            header = self._git.status_header(folder)
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

    def _check_remote(self, refs: Refs, names: list[str]) -> list[Finding]:
        findings: list[Finding] = []
        for name in names:
            spec = self._catalogue.services[name]
            ref, where = refs[name]
            exists, detail = self._git.remote_has_ref(spec.git, ref)
            if exists is None:
                findings.append(Finding(ERROR, name, f"cannot reach {spec.git}: {detail}"))
            elif exists:
                findings.append(Finding(OK, name, f"{ref!r} exists on the remote ({where})"))
            elif re.fullmatch(r"[0-9a-f]{7,40}", ref):
                findings.append(Finding(WARNING, name, f"{ref!r} looks like a commit: ls-remote cannot confirm it (it is fetched at deploy)"))
            else:
                findings.append(Finding(ERROR, name, f"{ref!r} is not a branch or tag of {spec.git} ({where})"))
        return findings
