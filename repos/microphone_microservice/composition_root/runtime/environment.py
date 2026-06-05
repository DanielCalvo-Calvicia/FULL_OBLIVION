import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


SUPPORTED_ENVIRONMENTS = ("development", "staging", "production")
ENVIRONMENT_VARIABLES = ("APP_ENV", "VSCODE_ENV")
DEFAULT_ENVIRONMENT = "development"


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    environment: str
    source: str
    raw_value: Optional[str] = None
    launch_profile: Optional[str] = None


def resolve_runtime_config(
    process_env: Optional[Mapping[str, str]] = None,
    workspace_root: Optional[Path] = None,
) -> RuntimeConfig:
    """Resolve the runtime environment from process env and VS Code launch config."""
    env = os.environ if process_env is None else process_env
    root = workspace_root or _workspace_root()
    launch_profiles = _load_launch_profiles(root)
    launch_profile = _select_launch_profile(launch_profiles, env)

    candidates: list[tuple[Optional[str], str]] = []
    candidates.extend(_env_candidates(env, "process environment"))

    if launch_profile:
        profile_name = str(launch_profile.get("name", "unnamed profile"))
        profile_env = launch_profile.get("env")
        if isinstance(profile_env, dict):
            candidates.extend(_env_candidates(profile_env, f"launch profile env ({profile_name})"))

        env_file = launch_profile.get("envFile")
        if isinstance(env_file, str):
            env_file_values = _load_env_file(_resolve_workspace_path(env_file, root))
            candidates.extend(_env_candidates(env_file_values, f"launch profile envFile ({profile_name})"))

    for value, source in candidates:
        normalized = _normalize_environment(value)
        if normalized:
            return RuntimeConfig(
                environment=normalized,
                source=source,
                raw_value=value,
                launch_profile=_profile_name(launch_profile),
            )

    return RuntimeConfig(
        environment=DEFAULT_ENVIRONMENT,
        source="safe default",
        raw_value=None,
        launch_profile=_profile_name(launch_profile),
    )


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_launch_profiles(root: Path) -> list[dict]:
    launch_json = root / ".vscode" / "launch.json"
    if not launch_json.exists():
        return []

    try:
        with launch_json.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return []

    configurations = data.get("configurations", [])
    return [profile for profile in configurations if isinstance(profile, dict)]


def _select_launch_profile(
    profiles: list[dict],
    env: Mapping[str, str],
) -> Optional[dict]:
    profile_name = env.get("VSCODE_LAUNCH_PROFILE")
    if profile_name:
        for profile in profiles:
            if profile.get("name") == profile_name:
                return profile

    for value in _ordered_env_values(env):
        normalized = _normalize_environment(value)
        if not normalized:
            continue
        for profile in profiles:
            profile_env = profile.get("env")
            if not isinstance(profile_env, dict):
                continue
            profile_values = _ordered_env_values(profile_env)
            if any(_normalize_environment(profile_value) == normalized for profile_value in profile_values):
                return profile

    return profiles[0] if profiles else None


def _env_candidates(env: Mapping[str, str], source: str) -> list[tuple[Optional[str], str]]:
    return [(env.get(name), f"{source}:{name}") for name in ENVIRONMENT_VARIABLES if env.get(name)]


def _ordered_env_values(env: Mapping[str, str]) -> list[str]:
    return [env[name] for name in ENVIRONMENT_VARIABLES if env.get(name)]


def _normalize_environment(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    normalized = value.strip().lower()
    aliases = {
        "dev": "development",
        "debug": "development",
        "local": "development",
        "stage": "staging",
        "prod": "production",
    }
    normalized = aliases.get(normalized, normalized)

    if normalized in SUPPORTED_ENVIRONMENTS:
        return normalized

    return None


def _resolve_workspace_path(value: str, root: Path) -> Path:
    resolved = value.replace("${workspaceFolder}", str(root))
    return Path(resolved)


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")

    return values


def _profile_name(profile: Optional[dict]) -> Optional[str]:
    if not profile:
        return None
    name = profile.get("name")
    return str(name) if name else None
