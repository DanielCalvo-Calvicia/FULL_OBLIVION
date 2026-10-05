"""launch.py: the one-command launcher (file generation and secrets handling; deploys are tested elsewhere)."""

from __future__ import annotations

import argparse
import shutil
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import launch  # noqa: E402
from domain.errors import DeployError  # noqa: E402
from infrastructure.config.host_loader import load_host  # noqa: E402
from infrastructure.config.paths import ConfigPaths  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway config/ with the shipped layouts, so nothing of the real one is read or written."""
    paths = ConfigPaths(tmp_path / "config")
    shutil.copytree(ROOT / "config" / "layouts", paths.layouts)
    monkeypatch.setattr(launch, "PATHS", paths)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # ~/oblivion (clones, venvs, state) stays out of the real home
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    for key in ("OPENAI_API_KEY", *launch.AI_AGENT_KEYS):
        monkeypatch.delenv(key, raising=False)
    return paths


def local(paths: ConfigPaths, name: str) -> dict:
    path = paths.local / f"{name}.toml"
    return tomllib.loads(path.read_text(encoding="utf-8")).get("env", {}) if path.exists() else {}


# --------------------------------------------------------------------------- a first run creates the files


def test_the_generated_robot_file_is_the_all_in_one_layout_and_is_valid(sandbox):
    launch.ensure_files("local", dry_run=True, interactive=False)
    assert 'layout = "all-in-one"' in sandbox.robot.read_text()
    host = load_host("robot", launch.CATALOGUE, sandbox)
    assert set(host.services) == {"microphone", "stt", "tts", "speaker", "ai-agent", "stepper", "brain"}
    assert launch.SERVICES == tuple(launch.CATALOGUE.services)  # the list of services is not repeated here either
    assert host.bind == "127.0.0.1" and host.remote == {}  # nothing is exposed to the network by default


def test_a_branch_is_a_per_run_option_and_changes_every_service(sandbox):
    from domain.rules.branch_overrides import apply_branch_overrides

    launch.ensure_files("local", dry_run=True, interactive=False)
    host = apply_branch_overrides(load_host("robot", launch.CATALOGUE, sandbox), ["feature_x"])
    assert {i.branch for i in host.services.values()} == {"feature_x"}


def test_local_stt_engine_is_written_to_the_local_stt_file(sandbox):
    launch.ensure_files("local", dry_run=False, interactive=False)
    assert local(sandbox, "stt") == {"STT_ENGINE": "local"}


def test_the_key_comes_from_the_environment_and_is_stored_only_in_the_local_file(sandbox, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")

    notes = launch.ensure_files("openai", dry_run=False, interactive=False)

    assert local(sandbox, "stt") == {"OPENAI_API_KEY": "sk-test-123"}
    assert "sk-test-123" not in sandbox.robot.read_text() and not any("sk-test-123" in n for n in notes)
    # a second run keeps it and asks for nothing
    monkeypatch.delenv("OPENAI_API_KEY")
    launch.ensure_files("openai", dry_run=False, interactive=False)
    assert (sandbox.local / "stt.toml").read_text().count("OPENAI_API_KEY") == 1


def test_a_key_the_user_already_put_in_local_all_toml_is_found(sandbox):
    sandbox.local.mkdir(parents=True)
    (sandbox.local / "all.toml").write_text('[env]\nOPENAI_API_KEY = "sk-from-all"\n')
    launch.ensure_files("openai", dry_run=False, interactive=False)  # no error, nothing asked
    assert not (sandbox.local / "stt.toml").exists()


def test_a_missing_key_is_a_clear_error_when_nobody_can_be_asked(sandbox):
    with pytest.raises(DeployError, match=r"OpenAI API key.*config/local/stt.toml.*--stt local"):
        launch.ensure_files("openai", dry_run=False, interactive=False)


def test_local_engine_needs_no_key(sandbox):
    launch.ensure_files("local", dry_run=False, interactive=False)
    assert "OPENAI_API_KEY" not in local(sandbox, "stt")


def test_a_local_file_you_made_is_never_overwritten_or_appended_to(sandbox, monkeypatch):
    sandbox.local.mkdir(parents=True)
    (sandbox.local / "stt.toml").write_text("# mine\n[env]\nSTT_LANGUAGE = 'es'\n")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    with pytest.raises(DeployError, match=r"stt.toml exists but has no OPENAI_API_KEY"):
        launch.ensure_files("openai", dry_run=False, interactive=False)
    assert (sandbox.local / "stt.toml").read_text() == "# mine\n[env]\nSTT_LANGUAGE = 'es'\n"


def test_an_existing_robot_file_is_never_overwritten(sandbox):
    sandbox.robot.parent.mkdir(parents=True, exist_ok=True)
    sandbox.robot.write_text('layout = "speaker-on-pc"\n')
    launch.ensure_files("local", dry_run=False, interactive=False)
    assert sandbox.robot.read_text() == 'layout = "speaker-on-pc"\n'


def test_llm_keys_are_copied_from_the_environment_for_ai_agent_and_never_printed(sandbox, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-1")
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-test-2")

    notes = launch.ensure_files("local", dry_run=False, interactive=False)

    assert local(sandbox, "ai-agent") == {"GROQ_API_KEY": "gsk-test-1", "GOOGLE_API_KEY": "goog-test-2"}
    assert not any("gsk-test-1" in n or "goog-test-2" in n for n in notes)
    assert "gsk-test-1" not in sandbox.robot.read_text()
    assert not any(n.startswith("warning") for n in notes)
    launch.ensure_files("local", dry_run=False, interactive=False)  # a second run adds nothing
    assert (sandbox.local / "ai-agent.toml").read_text().count("GROQ_API_KEY") == 1


def test_a_missing_llm_key_is_a_warning_not_an_error(sandbox):
    notes = launch.ensure_files("local", dry_run=False, interactive=False)
    assert any(n.startswith("warning") and "ai-agent" in n for n in notes)


def test_the_files_with_keys_are_readable_only_by_their_owner(sandbox, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("no POSIX file modes on Windows")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    launch.ensure_files("openai", dry_run=False, interactive=False)
    assert (sandbox.local / "stt.toml").stat().st_mode & 0o777 == 0o600


# --------------------------------------------------------------------------- the options


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
    args = launch.build_parser().parse_args(launch.normalize(["--console", "errors"]))
    assert args.command == "up" and args.console == "errors"
    assert launch.build_parser().parse_args(["up"]).console in {"stream", "errors", "all"}


# --------------------------------------------------------------------------- with a robot.toml


def robot(paths: ConfigPaths, layout: str = "all-in-one", **addresses: str) -> None:
    paths.robot.parent.mkdir(parents=True, exist_ok=True)
    paths.robot.write_text(f'layout = "{layout}"\n[addresses]\n' + "".join(f'{m} = "{a}"\n' for m, a in addresses.items()))


def args(**values):
    return argparse.Namespace(**{"machine": None, **values})


def test_without_a_robot_file_the_first_run_creates_one(sandbox):
    assert launch.robot_machine(args()) is None


def test_a_layout_with_one_machine_is_that_machine(sandbox):
    robot(sandbox)
    assert launch.robot_machine(args()) == "robot"


def test_a_layout_with_several_machines_needs_to_be_told_which_one_this_is(sandbox):
    robot(sandbox, "speaker-on-pc", pc="10.0.0.1", pi="10.0.0.2")
    with pytest.raises(DeployError, match=r"has 2 machines \(pc, pi\).*--machine pc"):
        launch.robot_machine(args())
    assert launch.robot_machine(args(machine="pi")) == "pi"
    with pytest.raises(DeployError, match=r"machine 'laptop' is not in layout 'speaker-on-pc'"):
        launch.robot_machine(args(machine="laptop"))


def test_machine_without_a_robot_file_says_how_to_make_one(sandbox):
    with pytest.raises(DeployError, match="needs a config/robot.toml.*oblivion.py init"):
        launch.robot_machine(args(machine="pc"))


def keys(paths: ConfigPaths) -> None:
    """The keys a configured robot has: OpenAI for stt, one LLM provider for ai-agent."""
    paths.local.mkdir(parents=True, exist_ok=True)
    (paths.local / "all.toml").write_text('[env]\nOPENAI_API_KEY = "key-not-real"\n')
    (paths.local / "ai-agent.toml").write_text('[env]\nGROQ_API_KEY = "key-not-real"\n')


def test_a_dry_run_with_a_robot_file_deploys_every_service_it_lists_and_creates_no_files(sandbox, capsys):
    robot(sandbox)
    keys(sandbox)
    before = sorted(p.name for p in sandbox.local.iterdir())
    assert launch.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "layout 'all-in-one', machine 'robot' (settings and keys come from config/)" in out
    for service in ("brain", "microphone", "stt", "tts", "speaker", "ai-agent", "stepper"):
        assert f"{service}: code " in out, service
    assert sorted(p.name for p in sandbox.local.iterdir()) == before  # nothing generated, nothing prompted


def test_a_first_dry_run_creates_only_the_git_ignored_files_without_secrets(sandbox, capsys):
    assert launch.main(["--dry-run", "--stt", "local"]) == 0
    out = capsys.readouterr().out
    assert "created config/robot.toml (layout 'all-in-one'" in out
    assert sandbox.robot.exists()
    assert sorted(p.name for p in sandbox.local.iterdir()) == ["stt.toml"]  # the engine choice; no key was asked or written


def test_a_first_dry_run_without_a_key_says_which_one_is_missing(sandbox, capsys):
    assert launch.main(["--dry-run"]) == 1
    assert "OPENAI_API_KEY is required when STT_ENGINE=openai" in capsys.readouterr().out


def test_a_layout_with_several_machines_launches_the_one_you_name(sandbox, capsys):
    robot(sandbox, "speaker-on-pc", pc="10.0.0.1", pi="10.0.0.2")
    keys(sandbox)
    assert launch.main(["--dry-run", "--machine", "pc"]) == 0
    out = capsys.readouterr().out
    assert "speaker: code " in out and "brain: code " not in out  # the PC runs only the speaker


def test_stt_local_belongs_in_the_local_file_when_there_is_a_robot_file(sandbox, capsys):
    robot(sandbox)
    assert launch.main(["--dry-run", "--stt", "local"]) == 2
    assert "config/local/stt.toml" in capsys.readouterr().err


def test_status_and_stop_work_from_a_robot_file_alone(sandbox, capsys):
    robot(sandbox)
    assert launch.main(["status"]) == 1  # nothing is running: stopped, not an error message
    assert "stopped" in capsys.readouterr().out
    assert launch.main(["--dry-run", "stop"]) == 0


def test_status_without_a_robot_file_says_to_run_the_launcher(sandbox, capsys):
    assert launch.main(["status"]) == 2
    assert "nothing deployed yet" in capsys.readouterr().err
