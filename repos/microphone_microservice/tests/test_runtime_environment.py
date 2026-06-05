import json

from composition_root.runtime.environment import resolve_runtime_config
from composition_root.runtime.logger import Logger


def test_process_environment_takes_precedence(tmp_path):
    _write_launch_json(tmp_path, "staging")

    config = resolve_runtime_config(
        process_env={
            "APP_ENV": "production",
            "VSCODE_LAUNCH_PROFILE": "Python: Run (staging env)",
        },
        workspace_root=tmp_path,
    )

    assert config.environment == "production"
    assert config.source == "process environment:APP_ENV"


def test_launch_env_file_is_used_when_process_env_is_missing(tmp_path):
    env_file = tmp_path / ".env.staging"
    env_file.write_text("APP_ENV=staging\n", encoding="utf-8")
    _write_launch_json(tmp_path, None, env_file="${workspaceFolder}/.env.staging")

    config = resolve_runtime_config(
        process_env={"VSCODE_LAUNCH_PROFILE": "Python: Run (staging env)"},
        workspace_root=tmp_path,
    )

    assert config.environment == "staging"
    assert config.source == "launch profile envFile (Python: Run (staging env)):APP_ENV"


def test_invalid_environment_falls_back_to_development(tmp_path):
    _write_launch_json(tmp_path, "qa")

    config = resolve_runtime_config(
        process_env={"VSCODE_LAUNCH_PROFILE": "Python: Run (staging env)"},
        workspace_root=tmp_path,
    )

    assert config.environment == "development"
    assert config.source == "safe default"


def test_logger_filters_by_environment(capsys):
    logger = Logger("test")
    object.__setattr__(
        logger,
        "runtime_config",
        resolve_runtime_config(process_env={"APP_ENV": "staging"}),
    )

    logger.info("hidden")
    logger.warn("visible")

    captured = capsys.readouterr()
    assert "hidden" not in captured.out
    assert "WARN test - visible" in captured.out


def _write_launch_json(tmp_path, app_env, env_file=None):
    vscode_dir = tmp_path / ".vscode"
    vscode_dir.mkdir()
    env = {"VSCODE_LAUNCH_PROFILE": "Python: Run (staging env)"}
    if app_env is not None:
        env["APP_ENV"] = app_env

    profile = {
        "name": "Python: Run (staging env)",
        "type": "python",
        "request": "launch",
        "program": "${workspaceFolder}/main.py",
        "env": env,
    }
    if env_file:
        profile["envFile"] = env_file

    launch_json = {
        "version": "0.2.0",
        "configurations": [profile],
    }
    (vscode_dir / "launch.json").write_text(json.dumps(launch_json), encoding="utf-8")
