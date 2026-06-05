import os

from composition_root.dependencies.stt_dependency import generate_stt_dependency
from runtime.environment import apply_launch_environment


def _clear_env(monkeypatch) -> None:
    for key in (
        "APP_ENV",
        "VSCODE_ENV",
        "VSCODE_LAUNCH_PROFILE",
        "SERVICE_HOST",
        "SERVICE_PORT",
        "STT_ENGINE",
        "STT_LANGUAGE",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_apply_launch_environment_loads_workspace_env_without_launch_profile(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    workspace = tmp_path / "service"
    workspace.mkdir()
    (workspace / ".env").write_text(
        "APP_ENV=debug\n"
        "SERVICE_PORT=8001\n"
        "STT_ENGINE=local\n"
        "OPENAI_API_KEY=test-key\n",
        encoding="utf-8",
    )

    runtime_env = apply_launch_environment(workspace_root=workspace)

    assert runtime_env.name == "development"
    assert runtime_env.env_file == workspace / ".env"
    assert os.getenv("SERVICE_PORT") == "8001"
    assert os.getenv("STT_ENGINE") == "local"
    assert os.getenv("OPENAI_API_KEY") == "test-key"


def test_apply_launch_environment_loads_vscode_env_file(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    workspace = tmp_path / "service"
    vscode = workspace / ".vscode"
    vscode.mkdir(parents=True)
    (workspace / ".env").write_text("STT_ENGINE=local\n", encoding="utf-8")
    (vscode / "launch.json").write_text(
        """
        {
            "version": "0.2.0",
            "configurations": [
                {
                    "name": "Python: Debug",
                    "type": "debugpy",
                    "request": "launch",
                    "program": "${workspaceFolder}/main.py",
                    "env": {"APP_ENV": "development"},
                    "envFile": "${workspaceFolder}/.env"
                }
            ]
        }
        """,
        encoding="utf-8",
    )

    runtime_env = apply_launch_environment(workspace_root=workspace)

    assert runtime_env.name == "development"
    assert runtime_env.launch_profile == "Python: Debug"
    assert runtime_env.env_file == workspace / ".env"
    assert os.getenv("STT_ENGINE") == "local"


def test_apply_launch_environment_keeps_existing_process_values(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    workspace = tmp_path / "service"
    workspace.mkdir()
    (workspace / ".env").write_text("STT_ENGINE=local\n", encoding="utf-8")
    monkeypatch.setenv("STT_ENGINE", "openai")

    apply_launch_environment(workspace_root=workspace)

    assert os.getenv("STT_ENGINE") == "openai"


def test_generate_stt_dependency_loads_env_before_reading_getenv(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    workspace = tmp_path / "service"
    workspace.mkdir()
    (workspace / ".env").write_text(
        "STT_ENGINE=openai\n"
        "STT_LANGUAGE=es\n"
        "OPENAI_API_KEY=test-key\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "composition_root.dependencies.stt_dependency.apply_launch_environment",
        lambda: apply_launch_environment(workspace_root=workspace),
    )

    dependency = generate_stt_dependency()

    assert os.getenv("STT_ENGINE") == "openai"
    assert os.getenv("STT_LANGUAGE") == "es"
    assert os.getenv("OPENAI_API_KEY") == "test-key"
    assert dependency.adapter_outbound.language == "es"
    assert dependency.adapter_outbound.is_available is not None
