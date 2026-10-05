"""``--branch`` on the command line: put some or all services of a machine on another branch, tag or commit."""

from __future__ import annotations

from dataclasses import replace

from domain.entities.host import Host
from domain.errors import DeployError


def apply_branch_overrides(host: Host, overrides: list[str]) -> Host:
    """``--branch X`` (every service) or ``--branch svc=X`` (one service), repeatable. The command line wins over every file."""
    if not overrides:
        return host
    services = dict(host.services)
    for item in overrides:
        name, sep, ref = item.partition("=")
        if not sep:
            ref, targets = item, list(services)
        else:
            if name not in services:
                raise DeployError(f"--branch {item}: {name!r} is not deployed on machine {host.name!r}")
            targets = [name]
        for target in targets:
            services[target] = replace(services[target], branch=ref)
    return replace(host, services=services)
