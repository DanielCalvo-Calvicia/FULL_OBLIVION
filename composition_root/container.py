"""Wiring: the real adapters behind the ports, assembled into the use cases. The only place that knows both sides."""

from __future__ import annotations

from application.dtos.options import Options
from application.services.compat_service import CompatService
from application.services.deployment_service import DeploymentService
from domain.entities.catalogue import Catalogue
from domain.entities.host import Host
from infrastructure.outbound.env.dotenv_files import DotenvFiles
from infrastructure.outbound.git.git_source_control import GitSourceControl
from infrastructure.outbound.health.http_health import HttpHealth
from infrastructure.outbound.installer.native_installer import NativeInstaller
from infrastructure.outbound.runtime.process_runtime import ProcessRuntime
from infrastructure.outbound.shell.shell import Shell
from infrastructure.outbound.state.json_state import JsonState
from infrastructure.outbound.workspace.workspace_files import WorkspaceFiles


def new_deployment_service(
    host: Host, catalogue: Catalogue, options: Options | None = None, *, shell: Shell | None = None
) -> DeploymentService:
    """The use cases for one machine, on real git, real processes and real HTTP."""
    shell = shell or Shell()
    return DeploymentService(
        host,
        catalogue,
        options or Options(),
        shell=shell,
        git=GitSourceControl(shell),
        installer=NativeInstaller(shell),
        runtime=ProcessRuntime(shell),
        health=HttpHealth(),
        state=JsonState(host.state_dir()),
        env_files=DotenvFiles(),
    )


def new_compat_service(catalogue: Catalogue, shell: Shell | None = None) -> CompatService:
    return CompatService(catalogue, GitSourceControl(shell or Shell(echo=False)), WorkspaceFiles())
