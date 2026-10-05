"""config/services/<name>.toml and config/local/<name>.toml: which code a service runs and its own settings, one file each."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from conftest import Config, write_settings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import env_inventory  # noqa: E402

from domain.errors import DeployError  # noqa: E402
from infrastructure.config.paths import ConfigPaths  # noqa: E402
from infrastructure.config.settings_loader import load_settings, resolved_refs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent
needs_workspace = pytest.mark.skipif(
    not all((WORKSPACE / name).exists() for name in ("brain_microservice", "ai-agent", "stepper_microservice")),
    reason="no workspace next to this repository",
)


def load(config: Config, folder: str = "services"):
    return load_settings(config.paths.root / folder, config.paths, config.catalogue)


# --------------------------------------------------------------------------- reading the files


def test_a_settings_file_names_a_branch_a_tag_or_a_commit(config):
    write_settings(config.paths, "services", "tts", 'branch = "feature_x"\n[env]\nTTS_PIPER_SPEED = 1.1\n')
    write_settings(config.paths, "services", "stt", 'tag = "v1.2.0"\n')
    write_settings(config.paths, "services", "brain", 'commit = "0123abc"\n')
    files = load(config)
    assert (files["tts"].ref, files["tts"].ref_kind) == ("feature_x", "branch")
    assert files["tts"].env == {"TTS_PIPER_SPEED": "1.1"}
    assert (files["stt"].ref, files["stt"].ref_kind) == ("v1.2.0", "tag")
    assert (files["brain"].ref, files["brain"].ref_kind) == ("0123abc", "commit")
    assert files["tts"].label == "config/services/tts.toml"


def test_runtime_port_and_git_are_read(config):
    write_settings(config.paths, "local", "stt", 'runtime = "docker"\nport = 9001\ngit = "https://example.invalid/stt.git"\n')
    stt = load(config, "local")["stt"]
    assert (stt.runtime, stt.port, stt.git) == ("docker", 9001, "https://example.invalid/stt.git")


def test_no_settings_folder_means_no_settings(config):
    assert load(config) == {} and load(config, "local") == {}


def test_a_file_without_a_ref_follows_the_next_lower_one(config):
    write_settings(config.paths, "services", "tts", "[env]\nTTS_PIPER_SPEED = 1.1\n")
    assert load(config)["tts"].ref is None


def test_all_toml_is_the_shared_settings_file(config):
    write_settings(config.paths, "services", "all", "[env]\nLOG_LEVEL = 'WARNING'\n")
    assert load(config)["all"].env == {"LOG_LEVEL": "WARNING"}


@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        ("nothing", 'branch = "x"\n', "not a service of the catalogue"),
        ("tts", 'branch = "x"\ntag = "v1"\n', "only one of branch, tag or commit"),
        ("tts", 'brnach = "x"\n', "unknown key"),
        ("tts", 'branch = "two words"\n', "without spaces"),
        ("tts", 'branch = ""\n', "non-empty"),
        ("tts", "port = 'eighty'\n", "port must be a number"),
        ("tts", "port = true\n", "port must be a number"),
        ("tts", "[env]\nTTS_ENGINE = [1, 2]\n", "must be a string, a number or true/false"),
        ("tts", 'env = "oops"\n', "must be a table"),
        ("all", 'branch = "x"\n', "all.toml only has an \\[env\\] table"),
    ],
)
def test_mistakes_in_a_settings_file_stop_everything_with_a_clear_message(config, name, text, message):
    write_settings(config.paths, "services", name, text)
    with pytest.raises(DeployError, match=message):
        load(config)


def test_the_example_templates_are_not_read_as_settings(config):
    config.paths.local.mkdir(parents=True)
    (config.paths.local / "tts.example.toml").write_text('branch = "never-read"\n')
    assert load(config, "local") == {}


# --------------------------------------------------------------------------- which code runs


def test_the_catalogue_default_is_used_without_any_file(config):
    config.layout({"robot": ["tts"]})
    assert config.host("robot").services["tts"].branch == config.catalogue.services["tts"].branch


def test_a_settings_file_pins_one_service_and_leaves_the_others(config):
    config.layout({"robot": ["tts", "stt"]}).service("tts", 'tag = "v1.2.0"\n')
    host = config.host("robot")
    assert host.services["tts"].branch == "v1.2.0"
    assert host.services["stt"].branch == config.catalogue.services["stt"].branch


def test_a_settings_file_of_a_service_on_another_machine_is_not_applied_here(config):
    config.layout({"server": ["tts"], "pi": ["stepper"]}, {"server": "192.168.1.10", "pi": "192.168.1.30"})
    config.local("stepper", 'branch = "feature_pi"\n[env]\nMOCK_HARDWARE = 0\n')
    server = config.host("server")
    assert "stepper" not in server.services
    assert all("stepper" not in layer.label for service in server.services.values() for layer in service.layers)
    pi = config.host("pi")
    assert pi.services["stepper"].branch == "feature_pi"
    assert pi.services["stepper"].layers[-1].values == {"MOCK_HARDWARE": "0"}


def test_the_layers_of_a_service_are_in_priority_order_and_empty_files_are_skipped(config):
    config.layout({"robot": ["tts"]})
    config.service("all", "[env]\nLOG_LEVEL = 'INFO'\n")
    config.service("tts", 'branch = "x"\n')  # no [env]: no layer
    config.local("all", "[env]\nLOG_LEVEL = 'DEBUG'\n")
    config.local("tts", "[env]\nTTS_PIPER_SPEED = 1.3\n")
    labels = [layer.label for layer in config.host("robot").services["tts"].layers]
    assert labels == ["config/services/all.toml", "config/local/all.toml", "config/local/tts.toml"]


def test_the_refs_a_compat_check_reports_follow_the_same_priority(config):
    config.layout({"robot": ["tts", "stt"]})
    config.service("tts", 'branch = "from-services"\n')
    config.local("tts", 'tag = "v9"\n')
    config.service("stt", 'branch = "stt-branch"\n')
    refs = resolved_refs(config.paths, config.catalogue)
    assert refs["tts"] == ("v9", "config/local/tts.toml (tag)")
    assert refs["stt"] == ("stt-branch", "config/services/stt.toml (branch)")
    assert refs["brain"] == (config.catalogue.services["brain"].branch, "config/catalogue.toml")


# --------------------------------------------------------------------------- the committed files


@needs_workspace
def test_the_committed_settings_files_are_current():
    for relative, text in env_inventory.build_files().items():
        committed = (ROOT / "config" / relative).read_text(encoding="utf-8").replace("\r\n", "\n")
        assert committed == text, f"config/{relative.as_posix()} is out of date: run scripts/env_inventory.py --write"
    assert env_inventory.main(["--check"]) == 0


def test_every_service_has_a_settings_file_and_the_shared_one(catalogue):
    committed = {p.stem for p in (ROOT / "config" / "services").glob("*.toml")}
    assert committed == {*catalogue.services, "all"}


def test_the_committed_defaults_change_nothing_until_a_line_is_uncommented(catalogue):
    files = load_settings(ROOT / "config" / "services", ConfigPaths(), catalogue)
    assert set(files) == {*catalogue.services, "all"}
    assert all(f.ref is None and f.runtime is None and f.port is None and f.git is None for f in files.values())
    assert all(f.env == {} for f in files.values()), {n: f.env for n, f in files.items() if f.env}


def test_secrets_are_never_active_in_a_committed_file():
    for path in (ROOT / "config" / "services").glob("*.toml"):
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not line.strip().endswith('= ""') or line.lstrip().startswith("#"), f"{path.name}: {line}"


def test_every_local_example_is_valid_when_copied_as_it_is(tmp_path, catalogue):
    config = Config(tmp_path, catalogue)
    config.paths.local.mkdir(parents=True)
    examples = sorted((ROOT / "config" / "local").glob("*.example.toml"))
    assert examples, "no local examples shipped"
    for example in examples:
        shutil.copy(example, config.paths.local / example.name.replace(".example", ""))
    files = load(config, "local")
    assert files["all"].env == {"OPENAI_API_KEY": ""}  # the shared key
    assert files["ai-agent"].env["GROQ_API_KEY"] == ""  # the secrets are listed active and empty
    assert all(f.ref is None for f in files.values())
    assert set(files) <= {*catalogue.services, "all"}
