"""launch.py: the one-command launcher (file generation and secrets handling; deploys are tested elsewhere)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import launch  # noqa: E402
from oblivion.config import DeployError, load_host, load_registry  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "HOST_FILE", tmp_path / "hosts" / "local.toml")
    monkeypatch.setattr(launch, "SECRETS_FILE", tmp_path / "secrets" / "local.env")
    for key in ("OPENAI_API_KEY", *launch.AI_AGENT_KEYS):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def test_the_generated_host_file_is_valid_and_runs_every_service_on_the_chosen_branch():
    text = launch.host_file_text("feature_x", "openai")
    registry = load_registry(launch.ROOT / "services.toml")
    path = Path(launch.ROOT / "hosts" / "_generated_for_test.toml")
    path.write_text(text)
    try:
        host = load_host(str(path), registry)
    finally:
        path.unlink()
    assert set(host.services) == {"microphone", "stt", "tts", "speaker", "ai-agent", "stepper", "brain"}
    assert set(host.services["ai-agent"].env) == {"GROQ_URL", "GOOGLE_URL"}
    assert {i.branch for i in host.services.values()} == {"feature_x"}
    assert host.bind == "127.0.0.1"  # nothing is exposed to the network by default


def test_local_stt_engine_is_written_into_the_host_file():
    assert 'STT_ENGINE = "local"' in launch.host_file_text("main", "local")
    assert "STT_ENGINE" not in launch.host_file_text("main", "openai")


def test_the_key_comes_from_the_environment_and_is_stored_only_in_the_secrets_file(sandbox, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")

    notes = launch.ensure_files("main", "openai", dry_run=False, interactive=False)

    assert launch.read_secret_key(launch.SECRETS_FILE, "STT__OPENAI_API_KEY") == "sk-test-123"
    assert "sk-test-123" not in launch.HOST_FILE.read_text() and not any("sk-test-123" in n for n in notes)
    # a second run keeps it and asks for nothing
    monkeypatch.delenv("OPENAI_API_KEY")
    launch.ensure_files("main", "openai", dry_run=False, interactive=False)
    assert launch.SECRETS_FILE.read_text().count("STT__OPENAI_API_KEY") == 1


def test_a_missing_key_is_a_clear_error_when_nobody_can_be_asked(sandbox):
    with pytest.raises(DeployError, match="OpenAI API key.*--stt local"):
        launch.ensure_files("main", "openai", dry_run=False, interactive=False)


def test_local_engine_needs_no_key(sandbox):
    launch.ensure_files("main", "local", dry_run=False, interactive=False)
    assert not launch.SECRETS_FILE.exists()


def test_an_existing_host_file_is_never_overwritten(sandbox):
    launch.HOST_FILE.parent.mkdir()
    launch.HOST_FILE.write_text("# mine\n")
    launch.ensure_files("main", "local", dry_run=False, interactive=False)
    assert launch.HOST_FILE.read_text() == "# mine\n"


def test_options_work_without_the_up_command():
    assert launch.normalize([]) == ["up"]
    assert launch.normalize(["--branch", "feature_ai_claude"]) == ["up", "--branch", "feature_ai_claude"]
    assert launch.normalize(["--dry-run", "--stt", "local"]) == ["--dry-run", "up", "--stt", "local"]
    assert launch.normalize(["status"]) == ["status"]
    assert launch.normalize(["--help"]) == ["--help"]

    parser = launch.build_parser()
    args = parser.parse_args(launch.normalize(["--branch", "x", "--no-update", "--dry-run"]))
    assert (args.command, args.branch, args.no_update, args.dry_run) == ("up", "x", True, True)
    assert parser.parse_args(["up", "--dry-run"]).dry_run is True  # also after the command
    assert parser.parse_args(["logs", "stt"]).service == "stt"


def test_console_level_is_an_option_of_up():
    import launch

    args = launch.build_parser().parse_args(launch.normalize(["--console", "errors"]))
    assert args.command == "up" and args.console == "errors"
    assert launch.build_parser().parse_args(["up"]).console in {"stream", "errors", "all"}


def test_llm_keys_are_copied_from_the_environment_for_ai_agent_and_never_printed(sandbox, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-1")
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-test-2")

    notes = launch.ensure_files("main", "local", dry_run=False, interactive=False)

    assert launch.read_secret_key(launch.SECRETS_FILE, "AI_AGENT__GROQ_API_KEY") == "gsk-test-1"
    assert launch.read_secret_key(launch.SECRETS_FILE, "AI_AGENT__GOOGLE_API_KEY") == "goog-test-2"
    assert not any("gsk-test-1" in n or "goog-test-2" in n for n in notes)
    assert "gsk-test-1" not in launch.HOST_FILE.read_text()
    assert not any(n.startswith("warning") for n in notes)
    launch.ensure_files("main", "local", dry_run=False, interactive=False)  # a second run adds nothing
    assert launch.SECRETS_FILE.read_text().count("AI_AGENT__GROQ_API_KEY") == 1


def test_a_missing_llm_key_is_a_warning_not_an_error(sandbox):
    notes = launch.ensure_files("main", "local", dry_run=False, interactive=False)
    assert any(n.startswith("warning") and "ai-agent" in n for n in notes)
