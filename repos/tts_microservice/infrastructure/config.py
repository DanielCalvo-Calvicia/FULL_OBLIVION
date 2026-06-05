import json
import os
from pathlib import Path
from typing import Any

SUPPORTED_ENVIRONMENTS = {"development", "staging", "production"}
DEFAULT_ENVIRONMENT = "development"
ENVIRONMENT_VARIABLE_PRECEDENCE = ("VSCODE_ENV", "APP_ENV")
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
LAUNCH_CONFIG_PATH = WORKSPACE_ROOT / ".vscode" / "launch.json"


def _normalize_environment(value: str | None) -> str | None:
    if not value:
        return None

    normalized = value.strip().lower()
    aliases = {
        "dev": "development",
        "debug": "development",
        "stage": "staging",
        "prod": "production",
    }
    return aliases.get(normalized, normalized)


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    return values


def _resolve_workspace_path(path_value: str) -> Path:
    return Path(path_value.replace("${workspaceFolder}", str(WORKSPACE_ROOT)))


def _load_launch_config() -> dict[str, Any]:
    if not LAUNCH_CONFIG_PATH.exists():
        return {}

    return json.loads(LAUNCH_CONFIG_PATH.read_text(encoding="utf-8"))


def get_launch_profiles() -> list[dict[str, Any]]:
    launch_config = _load_launch_config()
    return launch_config.get("configurations", [])


def get_launch_profile_environment(profile: dict[str, Any]) -> dict[str, str]:
    env_file_values: dict[str, str] = {}
    env_file = profile.get("envFile")
    if env_file:
        env_file_values = _read_env_file(_resolve_workspace_path(env_file))

    profile_env = profile.get("env", {})
    return {**env_file_values, **profile_env}


def get_launch_profile_env_file(profile: dict[str, Any]) -> Path | None:
    env_file = profile.get("envFile")
    if not env_file:
        return None

    return _resolve_workspace_path(env_file)


def _environment_from_values(values: dict[str, str]) -> str | None:
    for variable_name in ENVIRONMENT_VARIABLE_PRECEDENCE:
        normalized = _normalize_environment(values.get(variable_name))
        if normalized in SUPPORTED_ENVIRONMENTS:
            return normalized
    return None


def get_launch_environment_map() -> dict[str, str]:
    environment_map: dict[str, str] = {}
    for profile in get_launch_profiles():
        profile_name = profile.get("name")
        if not profile_name:
            continue

        profile_environment = _environment_from_values(
            get_launch_profile_environment(profile)
        )
        environment_map[profile_name] = profile_environment or DEFAULT_ENVIRONMENT

    return environment_map


def get_runtime_env_file_path(environment: str | None = None) -> Path | None:
    resolved_environment = environment or resolve_environment()
    launch_profile_name = os.getenv("VSCODE_LAUNCH_PROFILE")
    fallback_profile: dict[str, Any] | None = None

    for profile in get_launch_profiles():
        profile_name = profile.get("name")
        profile_environment = _environment_from_values(
            get_launch_profile_environment(profile)
        )

        if profile_name == launch_profile_name:
            return get_launch_profile_env_file(profile)

        if profile_environment == resolved_environment and fallback_profile is None:
            fallback_profile = profile

    if fallback_profile is not None:
        return get_launch_profile_env_file(fallback_profile)

    default_env_file = WORKSPACE_ROOT / ".env"
    return default_env_file if default_env_file.exists() else None


def resolve_environment() -> str:
    process_values = {
        variable_name: os.getenv(variable_name, "")
        for variable_name in ENVIRONMENT_VARIABLE_PRECEDENCE
    }
    process_environment = _environment_from_values(process_values)
    if process_environment:
        return process_environment

    launch_profile_name = os.getenv("VSCODE_LAUNCH_PROFILE")
    if launch_profile_name:
        return get_launch_environment_map().get(
            launch_profile_name,
            DEFAULT_ENVIRONMENT,
        )

    return DEFAULT_ENVIRONMENT
