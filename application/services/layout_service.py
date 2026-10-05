"""``oblivion topology``: the whole robot as the layout describes it, and whether every machine can find what it needs."""

from __future__ import annotations

from domain.entities.catalogue import Catalogue
from domain.entities.host import Host
from domain.entities.layout import Layout
from domain.rules.host_validation import validate_host
from domain.rules.topology import exposed_services


def describe_layout(layout: Layout, catalogue: Catalogue, hosts: dict[str, Host]) -> tuple[list[str], int]:
    """``(lines to print, number of errors)``. ``hosts`` has one entry per machine of the layout."""
    lines = [f"layout {layout.name!r}: {len(layout.machines)} machine(s)" + (f" - {layout.description}" if layout.description else "")]
    problems = 0
    for machine in layout.machines.values():
        host = hosts[machine.name]
        exposed = exposed_services(layout, catalogue, machine)
        lines.append(f"\n  {machine.name}  {machine.address}   bind {host.bind}")
        for service, instance in host.services.items():
            marker = "  <- called from other machines" if service in exposed else ""
            lines.append(f"      runs   {service:<10} port {instance.port}{marker}")
        consumed = {target for service in host.services for target in catalogue.services[service].consumes}
        for service in sorted(consumed & set(host.remote)):
            lines.append(f"      calls  {service:<10} {host.remote[service]}")
        errors, _ = validate_host(host)
        for error in errors:
            problems += 1
            lines.append(f"      ERROR  {error}")
    unplaced = sorted(set(catalogue.services) - {s for m in layout.machines.values() for s in m.services})
    if unplaced:
        lines.append(f"\n  not placed on any machine: {', '.join(unplaced)}")
    lines.append("\nOK" if not problems else f"\n{problems} error(s)")
    return lines, problems
