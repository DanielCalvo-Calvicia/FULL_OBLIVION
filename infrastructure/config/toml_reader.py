"""Reading TOML files with errors the operator can act on."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from domain.errors import DeployError


def read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as error:
        raise DeployError(f"file not found: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise DeployError(f"{path}: invalid TOML: {error}") from error


def env_text(value: object, where: str) -> str:
    """A TOML value as the text of an environment variable: ``true`` -> ``true``, ``15`` -> ``15``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise DeployError(f"{where}: must be a string, a number or true/false, not {type(value).__name__}")


def check_keys(path: Path, data: dict[str, Any], allowed: set[str], hint: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise DeployError(f"{path}: unknown key(s) {', '.join(unknown)} ({hint})")
