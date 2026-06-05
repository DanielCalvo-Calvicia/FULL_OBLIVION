import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SUPPORTED_ENVIRONMENTS = ("development", "staging", "production")
DEFAULT_ENVIRONMENT = "development"
ENVIRONMENT_VARIABLES = ("APP_ENV", "VSCODE_ENV")
LAUNCH_PROFILE_VARIABLE = "VSCODE_LAUNCH_PROFILE"


@dataclass(frozen=True, slots=True)
class RuntimeEnvironment:
    name: str
    source: str
    raw_value: str | None = None


def resolve_runtime_environment(
    project_root: Path | None = None,
    process_env: Mapping[str, str] | None = None,
) -> RuntimeEnvironment:
    """Resolve the current runtime environment from process and VS Code launch data."""
    root = project_root or Path(__file__).resolve().parents[1]
    env = process_env or os.environ

    for key in ENVIRONMENT_VARIABLES:
        resolved = _validated_environment(env.get(key), f"process environment {key}")
        if resolved:
            return resolved

    launch_profile = _select_launch_profile(root, env)
    if launch_profile:
        profile_name = str(launch_profile.get("name", "unnamed launch profile"))
        profile_env = launch_profile.get("env") or {}
        if isinstance(profile_env, dict):
            for key in ENVIRONMENT_VARIABLES:
                resolved = _validated_environment(
                    profile_env.get(key),
                    f"VS Code launch profile '{profile_name}' env.{key}",
                )
                if resolved:
                    return resolved

        env_file = launch_profile.get("envFile")
        if isinstance(env_file, str):
            env_file_values = _read_env_file(_resolve_launch_path(env_file, root))
            for key in ENVIRONMENT_VARIABLES:
                resolved = _validated_environment(
                    env_file_values.get(key),
                    f"VS Code launch profile '{profile_name}' envFile {key}",
                )
                if resolved:
                    return resolved

    return RuntimeEnvironment(
        name=DEFAULT_ENVIRONMENT,
        source="safe default fallback",
        raw_value=None,
    )


def _validated_environment(value: object, source: str) -> RuntimeEnvironment | None:
    if not isinstance(value, str) or not value.strip():
        return None

    normalized = value.strip().lower()
    if normalized in SUPPORTED_ENVIRONMENTS:
        return RuntimeEnvironment(name=normalized, source=source, raw_value=value)

    return None


def _select_launch_profile(root: Path, env: Mapping[str, str]) -> dict | None:
    launch_json = root / ".vscode" / "launch.json"
    if not launch_json.exists():
        return None

    try:
        data = json.loads(launch_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    configurations = data.get("configurations", [])
    if not isinstance(configurations, list):
        return None

    named_profile = env.get(LAUNCH_PROFILE_VARIABLE)
    if named_profile:
        for profile in configurations:
            if isinstance(profile, dict) and profile.get("name") == named_profile:
                return profile

    matching_profiles = [
        profile
        for profile in configurations
        if isinstance(profile, dict)
        and _resolve_launch_path(str(profile.get("program", "")), root) == root / "main.py"
    ]
    if len(matching_profiles) == 1:
        return matching_profiles[0]

    return configurations[0] if len(configurations) == 1 and isinstance(configurations[0], dict) else None


def _resolve_launch_path(value: str, root: Path) -> Path:
    resolved = value.replace("${workspaceFolder}", str(root))
    return Path(resolved).resolve()


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip().strip("'\"")
    return values
