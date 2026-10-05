"""One service's settings file (``config/services/<name>.toml`` or ``config/local/<name>.toml``)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServiceSettings:
    service: str  # a service name, or "all" for all.toml
    label: str  # how messages name the file, e.g. "local/stt.toml"
    ref: str | None = None  # the branch, tag or commit; None = follow the next lower file or the catalogue
    ref_kind: str | None = None  # "branch", "tag" or "commit"
    runtime: str | None = None  # "native" or "docker"
    port: int | None = None
    git: str | None = None  # a clone URL or a local checkout to deploy instead of the catalogue's
    env: dict[str, str] = field(default_factory=dict)  # [env]: the settings
