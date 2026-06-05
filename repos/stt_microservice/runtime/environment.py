import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values


SUPPORTED_ENVIRONMENTS = ("development", "staging", "production")
DEFAULT_ENVIRONMENT = "development"
ENVIRONMENT_VARIABLES = ("APP_ENV", "VSCODE_ENV")


@dataclass(slots=True, frozen=True)
class LaunchProfile:
    name: str
    env: dict[str, str]
    env_file: Path | None


@dataclass(slots=True, frozen=True)
class RuntimeEnvironment:
    name: str
    source: str
    launch_profile: str | None
    env_file: Path | None


def apply_launch_environment(workspace_root: Path | None = None) -> RuntimeEnvironment:
    """Apply envFile and env values from the active VS Code launch profile.

    Precedence is:
    1. Existing process environment.
    2. Active launch profile env.
    3. Active launch profile envFile, or the workspace .env file.
    4. Safe default.
    """
    root = workspace_root or _default_workspace_root()
    original_process_env = dict(os.environ)
    profiles = _read_launch_profiles(root)
    profile = _select_launch_profile(profiles, original_process_env)
    env_file = _select_env_file(root, profile)
    env_file_values = dotenv_values(env_file) if env_file and env_file.exists() else {}

    for key, value in env_file_values.items():
        if value is not None and key not in os.environ:
            os.environ[key] = value

    if profile:
        for key, value in profile.env.items():
            if key not in original_process_env:
                os.environ[key] = value

    runtime_env = resolve_runtime_environment(
        process_env=original_process_env,
        launch_env=profile.env if profile else {},
        env_file_values=env_file_values,
        launch_profile_name=profile.name if profile else None,
        env_file=env_file,
    )
    os.environ["APP_ENV"] = runtime_env.name
    return runtime_env


def resolve_runtime_environment(
    process_env: Mapping[str, str] | None = None,
    launch_env: Mapping[str, str] | None = None,
    env_file_values: Mapping[str, str | None] | None = None,
    launch_profile_name: str | None = None,
    env_file: Path | None = None,
) -> RuntimeEnvironment:
    process_env = os.environ if process_env is None else process_env
    launch_env = {} if launch_env is None else launch_env
    env_file_values = {} if env_file_values is None else env_file_values

    candidates = (
        ("process environment", process_env),
        ("VS Code launch env", launch_env),
        ("VS Code launch envFile", env_file_values),
    )

    for source, values in candidates:
        for variable in ENVIRONMENT_VARIABLES:
            value = values.get(variable)
            normalized = _normalize_environment(value)
            if normalized:
                return RuntimeEnvironment(normalized, f"{source}:{variable}", launch_profile_name, env_file)

    return RuntimeEnvironment(DEFAULT_ENVIRONMENT, "safe default", launch_profile_name, env_file)


def _normalize_environment(value: str | None) -> str | None:
    if not value:
        return None

    normalized = value.strip().lower()
    if normalized == "debug":
        normalized = "development"

    return normalized if normalized in SUPPORTED_ENVIRONMENTS else None


def _read_launch_profiles(workspace_root: Path) -> list[LaunchProfile]:
    launch_path = workspace_root / ".vscode" / "launch.json"
    if not launch_path.exists():
        return []

    data = json.loads(launch_path.read_text(encoding="utf-8"))
    profiles = []
    for config in data.get("configurations", []):
        env_file = config.get("envFile")
        profiles.append(
            LaunchProfile(
                name=config.get("name", "Unnamed launch profile"),
                env={str(key): str(value) for key, value in config.get("env", {}).items()},
                env_file=_resolve_vscode_path(env_file, workspace_root) if env_file else None,
            )
        )
    return profiles


def _select_launch_profile(
    profiles: list[LaunchProfile],
    process_env: Mapping[str, str],
) -> LaunchProfile | None:
    if not profiles:
        return None

    requested_profile = process_env.get("VSCODE_LAUNCH_PROFILE")
    if requested_profile:
        for profile in profiles:
            if profile.name == requested_profile:
                return profile

    process_environment = resolve_runtime_environment(process_env=process_env).name
    for profile in profiles:
        profile_environment = resolve_runtime_environment(process_env={}, launch_env=profile.env).name
        if profile_environment == process_environment:
            return profile

    return profiles[0]


def _resolve_vscode_path(value: str, workspace_root: Path) -> Path:
    return Path(value.replace("${workspaceFolder}", str(workspace_root))).resolve()


def _default_workspace_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _select_env_file(workspace_root: Path, profile: LaunchProfile | None) -> Path | None:
    if profile and profile.env_file:
        return profile.env_file

    default_env_file = workspace_root / ".env"
    return default_env_file if default_env_file.exists() else None
