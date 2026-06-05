import json
import os
from pathlib import Path

import pytest

from composition_root.environment import apply_launch_environment, normalize_environment, resolve_runtime_environment


@pytest.fixture(autouse=True)
def clean_runtime_environment(monkeypatch) -> None:
    for key in ("APP_ENV", "VSCODE_ENV", "VSCODE_LAUNCH_PROFILE", "SERVICE_PORT"):
        monkeypatch.delenv(key, raising=False)


def test_normalize_environment_supports_legacy_debug_alias() -> None:
    assert normalize_environment("debug") == "development"
    assert normalize_environment("development") == "development"
    assert normalize_environment("staging") == "staging"
    assert normalize_environment("production") == "production"
    assert normalize_environment("invalid") is None


def test_resolve_runtime_environment_prefers_app_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("VSCODE_ENV", "production")

    runtime_environment = resolve_runtime_environment()

    assert runtime_environment.value == "staging"
    assert runtime_environment.source == "APP_ENV"


def test_resolve_runtime_environment_defaults_to_development_for_invalid_value(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "qa")

    runtime_environment = resolve_runtime_environment()

    assert runtime_environment.value == "development"
    assert runtime_environment.used_default is True


def test_apply_launch_environment_uses_profile_env_over_env_file(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=development\nSERVICE_PORT=8005\n", encoding="utf-8")
    launch_dir = tmp_path / ".vscode"
    launch_dir.mkdir()
    (launch_dir / "launch.json").write_text(
        json.dumps(
            {
                "version": "0.2.0",
                "configurations": [
                    {
                        "name": "Python: Run (staging env)",
                        "env": {
                            "APP_ENV": "staging",
                            "VSCODE_LAUNCH_PROFILE": "Python: Run (staging env)",
                        },
                        "envFile": "${workspaceFolder}/.env",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = apply_launch_environment(tmp_path)

    assert summary.selected_profile == "Python: Run (staging env)"
    assert os.environ["APP_ENV"] == "staging"
    assert os.environ["SERVICE_PORT"] == "8005"


def test_apply_launch_environment_keeps_process_environment_highest_precedence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=development\nSERVICE_PORT=8005\n", encoding="utf-8")
    launch_dir = tmp_path / ".vscode"
    launch_dir.mkdir()
    (launch_dir / "launch.json").write_text(
        json.dumps(
            {
                "version": "0.2.0",
                "configurations": [
                    {
                        "name": "Python: Run (staging env)",
                        "env": {"APP_ENV": "staging"},
                        "envFile": "${workspaceFolder}/.env",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    apply_launch_environment(tmp_path)

    assert os.environ["APP_ENV"] == "production"
