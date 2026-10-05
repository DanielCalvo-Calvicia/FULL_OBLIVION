"""Checks of one machine's configuration that need no network and no clone."""

from __future__ import annotations

from urllib.parse import urlsplit

from domain.entities.host import RUNTIMES, Host


def validate_host(host: Host) -> tuple[list[str], list[str]]:
    """``(errors, warnings)``."""
    errors: list[str] = []
    warnings: list[str] = []
    ports: dict[int, str] = {}
    for name, instance in host.services.items():
        if instance.runtime not in RUNTIMES:
            errors.append(f"{name}: runtime must be one of {RUNTIMES}, not {instance.runtime!r}")
        if instance.runtime == "docker" and instance.spec.audio and host.os_family == "windows":
            errors.append(f"{name}: needs a sound device, which Docker cannot reach on Windows; use runtime = \"native\"")
        if instance.port in ports:
            errors.append(f"{name} and {ports[instance.port]} both use port {instance.port}")
        ports[instance.port] = name
        for target in instance.spec.consumes:
            if target in host.services or target in host.remote:
                continue
            if target in instance.spec.optional_consumes:
                warnings.append(f"{name}: optional service {target!r} is not in the layout; it will not be configured")
            else:
                errors.append(f"{name} needs {target!r}: put it on a machine of the layout (config/layouts/)")
    for target, url in host.remote.items():
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or any(c.isspace() for c in url):
            errors.append(f"remote {target}: {url!r} is not an address like 192.168.1.20, 192.168.1.20:8000 or http://192.168.1.20:8000")
        elif parsed.hostname in ("localhost", "127.0.0.1", "::1"):
            warnings.append(f"remote {target}: {url} points at this machine; a service on another machine needs its own address")
        if target in host.services:
            warnings.append(f"{target!r} is both local and remote; the local one is used")
    if not host.services:
        errors.append("this machine runs no services")
    if host.bind == "0.0.0.0":
        warnings.append("bind = 0.0.0.0 exposes the services on every network interface and they have no authentication")
    return errors, warnings
