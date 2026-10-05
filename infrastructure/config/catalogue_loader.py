"""``config/catalogue.toml``: what each service is (repository, port, requirements, what it calls)."""

from __future__ import annotations

from pathlib import Path

from domain.entities.catalogue import Catalogue
from domain.entities.service_spec import RequireRule, ServiceSpec
from domain.errors import DeployError
from infrastructure.config.paths import ConfigPaths
from infrastructure.config.toml_reader import read_toml


def _version(text: str) -> tuple[int, int]:
    major, _, minor = str(text).partition(".")
    return int(major), int(minor or 0)


def load_catalogue(paths: ConfigPaths | None = None, *, file: Path | None = None) -> Catalogue:
    paths = paths or ConfigPaths()
    path = file or paths.catalogue
    data = read_toml(path)
    services: dict[str, ServiceSpec] = {}
    for name, raw in data.get("services", {}).items():
        try:
            services[name] = ServiceSpec(
                name=name,
                git=raw["git"],
                branch=raw.get("branch", "main"),
                port=int(raw["port"]),
                health=raw.get("health", "/health"),
                ready=raw.get("ready"),
                entry=raw.get("entry", "main.py"),
                requirements=dict(raw.get("requirements", {})),
                libraries=tuple(raw.get("libraries", ())),
                apt=tuple(raw.get("apt", ())),
                prepare=tuple(raw.get("prepare", ())),
                audio=bool(raw.get("audio", False)),
                consumes=dict(raw.get("consumes", {})),
                optional_consumes=tuple(raw.get("optional_consumes", ())),
                env={k: str(v) for k, v in raw.get("env", {}).items()},
                require=tuple(
                    RequireRule(r["key"], {k: str(v) for k, v in r.get("when", {}).items()})
                    for r in raw.get("require", ())
                ),
                folder=raw.get("folder"),
                host_var=raw.get("host_var", "SERVICE_HOST"),
                port_var=raw.get("port_var", "SERVICE_PORT"),
                min_python=_version(raw["min_python"]) if "min_python" in raw else None,
                require_any=tuple(raw.get("require_any", ())),
                dotenv=bool(raw.get("dotenv", True)),
                extra_env=tuple(raw.get("extra_env", ())),
                internal=tuple(raw.get("internal", ())),
            )
        except KeyError as error:
            raise DeployError(f"{path}: service {name!r} is missing {error}") from error
    return Catalogue(services, dict(data.get("libraries", {})), paths.base_dir)
