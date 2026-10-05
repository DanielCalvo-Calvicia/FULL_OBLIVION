"""Build one machine (a ``Host``) from the files under ``config/``.

The machine is one of the layout's machines. Its services, their addresses and the URLs of the services on the other
machines come from the layout; each service's branch, runtime, port and settings come from its files, lowest first:

    catalogue.toml  <  services/<name>.toml  <  local/<name>.toml  <  --branch on the command line

Settings (``[env]``) are layered the same way, and ``all.toml`` in each folder holds what several services share.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from domain.entities.catalogue import Catalogue
from domain.entities.host import EnvLayer, Host, ServiceInstance
from domain.entities.layout import Layout
from domain.errors import DeployError
from domain.rules.topology import exposed_services, remote_urls
from infrastructure.config.layout_loader import load_layout
from infrastructure.config.machine_loader import detect_os, load_machine_settings
from infrastructure.config.paths import ConfigPaths
from infrastructure.config.settings_loader import ALL, load_settings


def load_host(machine_name: str, catalogue: Catalogue, paths: ConfigPaths, layout: Layout | None = None) -> Host:
    layout = layout or load_layout(paths, catalogue)
    if machine_name not in layout.machines:
        raise DeployError(
            f"machine {machine_name!r} is not in layout {layout.name!r} (machines: {', '.join(layout.machines)}); "
            f"pick one with --host, or change the layout in {paths.label(paths.robot)}"
        )
    machine = layout.machines[machine_name]
    settings = load_machine_settings(paths, machine_name)

    detected_os, detected_pi = detect_os()
    os_family = detected_os if settings.os == "auto" else ("linux" if settings.os == "raspberry" else settings.os)
    is_pi = detected_pi if settings.os == "auto" else settings.os == "raspberry"

    workdir = Path(settings.workdir or "~/oblivion").expanduser()
    if not workdir.is_absolute():
        workdir = (paths.root / workdir).resolve()

    project = load_settings(paths.services, paths, catalogue)
    local = load_settings(paths.local, paths, catalogue)

    instances: dict[str, ServiceInstance] = {}
    for name in machine.services:
        spec = catalogue.services[name]
        files = [f for f in (project.get(name), local.get(name)) if f is not None]  # lowest priority first
        ref = next((f.ref for f in reversed(files) if f.ref), None)
        git = next((f.git for f in reversed(files) if f.git), None)
        runtime = next((f.runtime for f in reversed(files) if f.runtime), "native")
        port = next((f.port for f in reversed(files) if f.port), machine.ports.get(name, spec.port))
        layers = tuple(
            EnvLayer(f.label, dict(f.env), shared=f.service == ALL)
            for f in (project.get(ALL), local.get(ALL), project.get(name), local.get(name))
            if f is not None and f.env
        )
        instances[name] = ServiceInstance(
            spec=replace(spec, git=git) if git else spec,  # e.g. a local checkout: deploy exactly what is committed there
            branch=ref or spec.branch,
            runtime=runtime,
            port=port,
            layers=layers,
        )

    bind = settings.bind or ("0.0.0.0" if exposed_services(layout, catalogue, machine) else "127.0.0.1")
    return Host(
        name=machine_name,
        os_family=os_family,
        is_raspberry=is_pi,
        workdir=workdir,
        bind=bind,
        python=settings.python,
        services=instances,
        remote=remote_urls(layout, catalogue, machine),
        config_dir=paths.root.resolve(),
        layout=layout.source,
    )
