"""Per-service settings files: ``config/services/<name>.toml`` (the project's defaults) and ``config/local/<name>.toml`` (yours).

Both have the same shape, and ``all.toml`` in each holds the ``[env]`` of variables several services share::

    branch = "feature_ai_claude_2"      # or tag = "v1.0.0", or commit = "0123abc" (at most one)
    runtime = "native"                  # or "docker"
    port = 8005                         # only to deviate from the catalogue
    git = "https://..."                 # only to deploy another repository or a local checkout
    [env]
    NAME = value                        # the service's own settings
"""

from __future__ import annotations

from pathlib import Path

from domain.entities.catalogue import Catalogue
from domain.entities.service_settings import ServiceSettings
from domain.errors import DeployError
from infrastructure.config.paths import ConfigPaths
from infrastructure.config.toml_reader import check_keys, env_text, read_toml

ALL = "all"  # all.toml: [env] for every service that uses the variable
REF_KEYS = ("branch", "tag", "commit")
SERVICE_KEYS = {*REF_KEYS, "runtime", "port", "git", "env"}


def load_settings(folder: Path, paths: ConfigPaths, catalogue: Catalogue) -> dict[str, ServiceSettings]:
    """Every ``<name>.toml`` of the folder (the ``*.example.toml`` templates are not read). A mistake stops everything."""
    files: dict[str, ServiceSettings] = {}
    if not folder.is_dir():
        return files
    for path in sorted(folder.glob("*.toml")):
        if path.name.endswith(".example.toml"):
            continue
        name = path.stem
        label = paths.label(path)
        if name != ALL and name not in catalogue.services:
            raise DeployError(f"{path}: {name!r} is not a service of the catalogue (known: {', '.join(sorted(catalogue.services))}; or all.toml)")
        data = read_toml(path)
        if name == ALL:
            check_keys(path, data, {"env"}, "all.toml only has an [env] table")
        else:
            check_keys(path, data, SERVICE_KEYS, "allowed: branch, tag or commit; runtime; port; git; and an [env] table")
        given = [key for key in REF_KEYS if key in data]
        if len(given) > 1:
            raise DeployError(f"{path}: set only one of branch, tag or commit (found {', '.join(given)})")
        ref, kind = None, None
        if given:
            value = str(data[given[0]]).strip()
            if not value or any(c.isspace() for c in value):
                raise DeployError(f"{path}: {given[0]} must be a non-empty name without spaces")
            ref, kind = value, given[0]
        env_table = data.get("env", {})
        if not isinstance(env_table, dict):
            raise DeployError(f"{path}: [env] must be a table of NAME = value")
        files[name] = ServiceSettings(
            service=name,
            label=label,
            ref=ref,
            ref_kind=kind,
            runtime=str(data["runtime"]) if "runtime" in data else None,
            port=_port(path, data["port"]) if "port" in data else None,
            git=str(data["git"]) if "git" in data else None,
            env={str(k): env_text(v, f"{path}: [env] {k}") for k, v in env_table.items()},
        )
    return files


def _port(path: Path, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 65536:
        raise DeployError(f"{path}: port must be a number between 1 and 65535, not {value!r}")
    return value


def resolved_refs(paths: ConfigPaths, catalogue: Catalogue) -> dict[str, tuple[str, str]]:
    """``{service: (ref, which file says so)}`` for a service deployed without ``--branch``: local file, then
    services file, then the catalogue's default branch."""
    project = load_settings(paths.services, paths, catalogue)
    local = load_settings(paths.local, paths, catalogue)
    refs: dict[str, tuple[str, str]] = {}
    for name, spec in catalogue.services.items():
        chosen = next((f for f in (local.get(name), project.get(name)) if f is not None and f.ref), None)
        refs[name] = (chosen.ref, f"{chosen.label} ({chosen.ref_kind})") if chosen else (spec.branch, "config/catalogue.toml")
    return refs
