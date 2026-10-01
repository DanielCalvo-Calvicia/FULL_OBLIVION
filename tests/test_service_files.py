"""services/<service>.toml: which code a service runs (branch, tag or commit) and its own settings, one file each."""

from __future__ import annotations

import shutil
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import env_inventory  # noqa: E402

from oblivion.config import DeployError, apply_branch_overrides, load_host, load_registry, load_service_files  # noqa: E402
from oblivion.envfile import LAYER_FILE, LAYER_ROBOT, LAYER_SERVICE, resolve_env  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent
needs_workspace = pytest.mark.skipif(
    not all((WORKSPACE / name).exists() for name in ("brain_microservice", "ai-agent", "stepper_microservice")),
    reason="no workspace next to this repository",
)

LAYOUT = """
[machines.server]
address = "192.168.1.10"
services = ["brain", "ai-agent", "stt", "tts"]
[machines.pc]
address = "192.168.1.20"
services = ["microphone", "speaker"]
[machines.pi]
address = "192.168.1.30"
services = ["stepper"]
"""


@pytest.fixture
def registry(tmp_path):
    return replace(load_registry(ROOT / "services.toml"), base_dir=tmp_path)


def service_file(tmp_path: Path, name: str, text: str) -> Path:
    folder = tmp_path / "services"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}.toml"
    path.write_text(textwrap.dedent(text))
    return path


def server(tmp_path: Path, registry, robot_extra: str = ""):
    (tmp_path / "robot.toml").write_text(LAYOUT + textwrap.dedent(robot_extra))
    return load_host("server", registry)


# --------------------------------------------------------------------------- reading the files


def test_a_service_file_names_a_branch_a_tag_or_a_commit(tmp_path, registry):
    service_file(tmp_path, "tts", 'branch = "feature_x"\n[env]\nTTS_PIPER_SPEED = 1.1\n')
    service_file(tmp_path, "stt", 'tag = "v1.2.0"\n')
    service_file(tmp_path, "brain", 'commit = "0123abc"\n')
    files = load_service_files(tmp_path, registry)
    assert (files["tts"].ref, files["tts"].ref_kind) == ("feature_x", "branch")
    assert files["tts"].env == {"TTS_PIPER_SPEED": "1.1"}
    assert (files["stt"].ref, files["stt"].ref_kind) == ("v1.2.0", "tag")
    assert (files["brain"].ref, files["brain"].ref_kind) == ("0123abc", "commit")


def test_no_services_folder_means_no_service_files(tmp_path, registry):
    assert load_service_files(tmp_path, registry) == {}


def test_a_file_without_a_ref_follows_the_default(tmp_path, registry):
    service_file(tmp_path, "tts", "[env]\nTTS_PIPER_SPEED = 1.1\n")
    assert load_service_files(tmp_path, registry)["tts"].ref is None


@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        ("nothing", 'branch = "x"\n', "not a service of the catalogue"),
        ("tts", 'branch = "x"\ntag = "v1"\n', "only one of branch, tag or commit"),
        ("tts", 'brnach = "x"\n', "unknown key"),
        ("tts", 'branch = "two words"\n', "without spaces"),
        ("tts", 'branch = ""\n', "non-empty"),
        ("tts", "[env]\nTTS_ENGINE = [1, 2]\n", "must be a string, a number or true/false"),
        ("tts", 'env = "oops"\n', "must be a table"),
    ],
)
def test_mistakes_in_a_service_file_stop_everything_with_a_clear_message(tmp_path, registry, name, text, message):
    service_file(tmp_path, name, text)
    with pytest.raises(DeployError, match=message):
        load_service_files(tmp_path, registry)


def test_the_example_templates_are_not_read_as_service_files(tmp_path, registry):
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "tts.example.toml").write_text('branch = "never-read"\n')
    assert load_service_files(tmp_path, registry) == {}


# --------------------------------------------------------------------------- which code runs


def test_the_registry_default_is_used_without_any_file(tmp_path, registry):
    host = server(tmp_path, registry)
    assert host.services["tts"].branch == registry.services["tts"].branch


def test_a_service_file_pins_one_service_and_leaves_the_others(tmp_path, registry):
    service_file(tmp_path, "tts", 'tag = "v1.2.0"\n')
    host = server(tmp_path, registry)
    assert host.services["tts"].branch == "v1.2.0"
    assert host.services["stt"].branch == registry.services["stt"].branch
    assert host.service_files["tts"].name == "tts.toml"


def test_priority_registry_then_host_default_then_service_file_then_host_service_then_command_line(tmp_path, registry):
    service_file(tmp_path, "tts", 'branch = "from-service-file"\n')
    robot = tmp_path / "robot.toml"
    robot.write_text(LAYOUT)
    host_file = tmp_path / "h.toml"

    host_file.write_text('[host]\nmachine = "server"\n[defaults]\nbranch = "from-host-default"\n')
    host = load_host(str(host_file), registry)
    assert host.services["tts"].branch == "from-service-file"  # the service's own file beats [defaults]
    assert host.services["stt"].branch == "from-host-default"  # the others follow [defaults]

    host_file.write_text('[host]\nmachine = "server"\n[defaults]\nbranch = "from-host-default"\n[services.tts]\nbranch = "from-host-service"\n')
    assert load_host(str(host_file), registry).services["tts"].branch == "from-host-service"

    overridden = apply_branch_overrides(load_host(str(host_file), registry), ["tts=from-cli"])
    assert overridden.services["tts"].branch == "from-cli"
    assert apply_branch_overrides(load_host(str(host_file), registry), ["everything"]).services["tts"].branch == "everything"


# --------------------------------------------------------------------------- the settings layer


def test_the_service_file_wins_over_robot_toml_and_loses_to_the_machine_env_file(tmp_path, registry):
    service_file(tmp_path, "tts", "[env]\nTTS_PIPER_SPEED = 1.3\nTTS_PITCH_SEMITONES = 3\n")
    host = server(tmp_path, registry, '[env.tts]\nTTS_PIPER_SPEED = 1.1\nTTS_DROID_EFFECT = 1\n')

    resolved = resolve_env(host, "tts", None)
    assert resolved.values["TTS_PIPER_SPEED"] == "1.3" and resolved.layer_of["TTS_PIPER_SPEED"] == LAYER_SERVICE
    assert resolved.values["TTS_PITCH_SEMITONES"] == "3" and resolved.layer_of["TTS_PITCH_SEMITONES"] == LAYER_SERVICE
    assert resolved.values["TTS_DROID_EFFECT"] == "1" and resolved.layer_of["TTS_DROID_EFFECT"] == LAYER_ROBOT

    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "server.env").write_text("TTS__TTS_PIPER_SPEED=1.5\n")
    host = load_host("server", registry)
    resolved = resolve_env(host, "tts", None)
    assert resolved.values["TTS_PIPER_SPEED"] == "1.5" and resolved.layer_of["TTS_PIPER_SPEED"] == LAYER_FILE


def test_a_service_file_of_a_service_on_another_machine_is_not_applied_here(tmp_path, registry):
    service_file(tmp_path, "stepper", 'branch = "feature_pi"\n[env]\nMOCK_HARDWARE = 0\n')
    host = server(tmp_path, registry)
    assert "stepper" not in host.services and "stepper" not in host.service_env
    pi = load_host("pi", registry)
    assert pi.services["stepper"].branch == "feature_pi"
    assert resolve_env(pi, "stepper", None).values["MOCK_HARDWARE"] == "0"


# --------------------------------------------------------------------------- the templates


@needs_workspace
def test_the_committed_service_templates_are_current():
    for name, text in env_inventory.build_service_templates().items():
        committed = (ROOT / "services" / f"{name}.example.toml").read_text(encoding="utf-8").replace("\r\n", "\n")
        assert committed == text, f"services/{name}.example.toml is out of date: run scripts/env_inventory.py --write"
    assert env_inventory.main(["--check"]) == 0


def test_every_template_is_valid_when_copied_as_it_is(tmp_path, registry):
    (tmp_path / "services").mkdir()
    for template in (ROOT / "services").glob("*.example.toml"):
        shutil.copy(template, tmp_path / "services" / template.name.replace(".example", ""))
    files = load_service_files(tmp_path, registry)
    assert set(files) == set(registry.services)  # one template per service of the catalogue
    assert all(f.ref is None for f in files.values())  # a copy changes nothing until a line is uncommented
    assert files["ai-agent"].env.get("GROQ_API_KEY") == ""  # the secrets are listed active and empty


def test_real_service_files_are_git_ignored_and_templates_are_not():
    patterns = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/services/*.toml" in patterns and "!/services/*.example.toml" in patterns
