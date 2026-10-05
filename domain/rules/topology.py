"""Who can reach whom: addresses, URLs, which services another machine calls."""

from __future__ import annotations

from domain.entities.catalogue import Catalogue
from domain.entities.host import Host, ServiceInstance
from domain.entities.layout import Layout, Machine


def url_host(address: str) -> str:
    """The address as it is written in a URL: an IPv6 address needs brackets."""
    return f"[{address.strip('[]')}]" if address.count(":") >= 2 else address


def service_port(layout: Layout, catalogue: Catalogue, service: str) -> int:
    machine = layout.machine_of(service)
    return machine.ports.get(service, catalogue.services[service].port) if machine else catalogue.services[service].port


def exposed_services(layout: Layout, catalogue: Catalogue, machine: Machine) -> list[str]:
    """The services of ``machine`` that a service on ANOTHER machine consumes: they must be reachable over the network."""
    return sorted({
        target
        for other in layout.machines.values() if other.name != machine.name
        for service in other.services
        for target in catalogue.services[service].consumes
        if target in machine.services
    })


def remote_urls(layout: Layout, catalogue: Catalogue, machine: Machine) -> dict[str, str]:
    """The base URL of every service that runs on a machine other than ``machine``."""
    return {
        service: f"http://{url_host(other.address)}:{service_port(layout, catalogue, service)}"
        for other in layout.machines.values() if other.name != machine.name
        for service in other.services
    }


def service_url(host: Host, consumer: ServiceInstance, target: str) -> str | None:
    """Base URL the ``consumer`` must use to reach ``target`` from this machine."""
    if target in host.services:
        port = host.services[target].port
        # A container reaches services published on the host through the special host name.
        address = "host.docker.internal" if consumer.runtime == "docker" else "127.0.0.1"
        return f"http://{address}:{port}"
    return host.remote.get(target)
