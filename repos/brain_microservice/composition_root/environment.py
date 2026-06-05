import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_ENVIRONMENTS = frozenset({"development", "staging", "production"})
DEFAULT_ENVIRONMENT = "development"
ENVIRONMENT_VARIABLES = ("APP_ENV", "VSCODE_ENV")
PROFILE_VARIABLE = "VSCODE_LAUNCH_PROFILE"
_ALIASES = {
    "debug": "development",
    "dev": "development",
    "prod": "production",
}


@dataclass(frozen=True, slots=True)
class RuntimeEnvironment:
    value: str
    source: str
    raw_value: str | None
    used_default: bool


@dataclass(frozen=True, slots=True)
class LaunchEnvironmentSummary:
    selected_profile: str | None
    env_file: str | None
    env_file_variables_loaded: int
    profile_variables_loaded: int


def apply_launch_environment(workspace_root: Path) -> LaunchEnvironmentSummary:
    profiles = _load_launch_profiles(workspace_root / ".vscode" / "launch.json")
    profile = _select_launch_profile(profiles)
    if profile is None:
        return LaunchEnvironmentSummary(None, None, 0, 0)

    process_variables = set(os.environ)
    env_file_loaded = 0
    env_file = _resolve_workspace_path(profile.get("envFile"), workspace_root)
    if env_file is not None and env_file.exists():
        for key, value in _read_env_file(env_file).items():
            if key not in process_variables:
                os.environ[key] = value
                env_file_loaded += 1

    profile_loaded = 0
    for key, value in _profile_env(profile).items():
        if key not in process_variables:
            os.environ[key] = value
            profile_loaded += 1

    return LaunchEnvironmentSummary(
        selected_profile=_profile_name(profile),
        env_file=str(env_file) if env_file is not None else None,
        env_file_variables_loaded=env_file_loaded,
        profile_variables_loaded=profile_loaded,
    )


def resolve_runtime_environment() -> RuntimeEnvironment:
    for variable in ENVIRONMENT_VARIABLES:
        raw_value = os.getenv(variable)
        if raw_value:
            resolved = normalize_environment(raw_value)
            if resolved is not None:
                return RuntimeEnvironment(
                    value=resolved,
                    source=variable,
                    raw_value=raw_value,
                    used_default=False,
                )
            return RuntimeEnvironment(
                value=DEFAULT_ENVIRONMENT,
                source=f"{variable} invalid",
                raw_value=raw_value,
                used_default=True,
            )

    return RuntimeEnvironment(
        value=DEFAULT_ENVIRONMENT,
        source="default",
        raw_value=None,
        used_default=True,
    )


def normalize_environment(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    normalized = _ALIASES.get(normalized, normalized)
    if normalized in SUPPORTED_ENVIRONMENTS:
        return normalized
    return None


def _load_launch_profiles(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    content = _strip_json_comments(path.read_text(encoding="utf-8"))
    launch_config = json.loads(content)
    configurations = launch_config.get("configurations", [])
    return tuple(profile for profile in configurations if isinstance(profile, dict))


def _select_launch_profile(profiles: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
    if not profiles:
        return None

    requested_profile = os.getenv(PROFILE_VARIABLE)
    if requested_profile:
        for profile in profiles:
            if _profile_name(profile) == requested_profile:
                return profile

    runtime_env = os.getenv("APP_ENV") or os.getenv("VSCODE_ENV")
    normalized_runtime_env = normalize_environment(runtime_env)
    if normalized_runtime_env is not None:
        for profile in profiles:
            for variable in ENVIRONMENT_VARIABLES:
                if normalize_environment(_profile_env(profile).get(variable)) == normalized_runtime_env:
                    return profile

    return profiles[0]


def _profile_name(profile: dict[str, Any]) -> str | None:
    name = profile.get("name")
    return name if isinstance(name, str) else None


def _profile_env(profile: dict[str, Any]) -> dict[str, str]:
    raw_env = profile.get("env", {})
    if not isinstance(raw_env, dict):
        return {}
    return {str(key): str(value) for key, value in raw_env.items() if value is not None}


def _resolve_workspace_path(value: Any, workspace_root: Path) -> Path | None:
    if not isinstance(value, str) or value == "":
        return None
    resolved = value.replace("${workspaceFolder}", str(workspace_root))
    return Path(resolved)


def _read_env_file(path: Path) -> dict[str, str]:
    variables: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        variables[key.strip()] = value.strip().strip('"').strip("'")
    return variables


def _strip_json_comments(content: str) -> str:
    without_block_comments = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", without_block_comments, flags=re.MULTILINE)
