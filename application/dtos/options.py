"""How one invocation of the tool behaves (the command-line flags that change the work, not what is deployed)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Options:
    force: bool = False
    system_deps: bool = False
    rollback: bool = True
    health_timeout: float = 60.0
    skip_health: bool = False
    remote_wait: float = 120.0  # seconds to wait for the required services of other machines before starting
