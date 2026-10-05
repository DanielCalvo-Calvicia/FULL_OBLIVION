"""Layouts, settings files, validation and environment layering: no network, no processes."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ALL_SERVICES, shipped_layout_hosts

from domain.errors import DeployError
from domain.rules.branch_overrides import apply_branch_overrides
from domain.rules.dotenv import parse_env
from domain.rules.env_names import mask
from domain.rules.env_resolution import resolve_env
from domain.rules.host_validation import validate_host

ROOT = Path(__file__).resolve().parent.parent


def test_the_shipped_catalogue_and_every_shipped_layout_are_valid(catalogue, tmp_path):
    assert {"brain", "microphone", "stt", "tts", "speaker", "stepper", "ai-agent"} <= set(catalogue.services)
    seen = list(shipped_layout_hosts(tmp_path, catalogue))
    assert {name for name, _, _ in seen} >= {"all-in-one", "speaker-on-pc", "audio-on-pc", "stepper-on-pi", "pc-server-pi"}
    for layout, machine, host in seen:
        errors, _ = validate_host(host)
        assert errors == [], f"{layout}/{machine}: {errors}"


def test_every_service_is_placed_exactly_once_in_every_shipped_layout(catalogue, tmp_path):
    placed: dict[str, list[str]] = {}
    for layout, _machine, host in shipped_layout_hosts(tmp_path, catalogue):
        placed.setdefault(layout, []).extend(host.services)
    for layout, services in placed.items():
        assert sorted(services) == sorted(catalogue.services), f"{layout}: {sorted(services)}"


# --------------------------------------------------------------------------- branch, runtime, port, git: file priority


def test_the_branch_comes_from_the_catalogue_then_services_then_local_then_the_command_line(config):
    config.layout({"robot": ["stt", "tts", "speaker"]})
    config.service("stt", 'branch = "feature_x"')
    config.service("tts", 'branch = "hotfix"')
    config.local("tts", 'branch = "mine"')  # yours wins over the project's
    host = config.host("robot")
    assert host.services["speaker"].branch == config.catalogue.services["speaker"].branch  # no file: the catalogue's
    assert (host.services["stt"].branch, host.services["tts"].branch) == ("feature_x", "mine")

    every = apply_branch_overrides(host, ["candidate"])
    assert {i.branch for i in every.services.values()} == {"candidate"}
    one = apply_branch_overrides(host, ["stt=abc123"])
    assert (one.services["stt"].branch, one.services["tts"].branch) == ("abc123", "mine")
    with pytest.raises(DeployError, match="not deployed"):
        apply_branch_overrides(host, ["brain=x"])


def test_a_tag_or_a_commit_can_replace_the_branch_in_a_settings_file(config):
    config.layout({"robot": ["stt", "tts"]})
    config.service("stt", 'tag = "v1.2.0"')
    config.local("tts", 'commit = "0123abc"')
    host = config.host("robot")
    assert (host.services["stt"].branch, host.services["tts"].branch) == ("v1.2.0", "0123abc")


def test_runtime_port_and_git_come_from_the_settings_files_and_the_local_file_wins(config, tmp_path):
    config.layout({"robot": ["stt", "tts"]})
    config.service("stt", 'runtime = "docker"\nport = 9001')
    config.local("stt", "port = 9002")
    config.service("tts", f'git = "{tmp_path.as_posix()}/my_tts"')
    host = config.host("robot")
    assert (host.services["stt"].runtime, host.services["stt"].port) == ("docker", 9002)
    assert host.services["tts"].spec.git == f"{tmp_path.as_posix()}/my_tts"
    assert host.services["stt"].spec.git == config.catalogue.services["stt"].git  # the others keep the catalogue's
    assert config.catalogue.services["tts"].git != host.services["tts"].spec.git  # the catalogue itself is untouched
    assert apply_branch_overrides(host, ["tts=x"]).services["tts"].spec.git == host.services["tts"].spec.git


def test_a_layouts_port_for_a_machine_is_followed_by_that_machine(config):
    config.layout({"robot": ["stt", "tts"]}, ports={"robot": {"stt": 18001}})
    assert config.host("robot").services["stt"].port == 18001
    assert config.host("robot").services["tts"].port == config.catalogue.services["tts"].port


# --------------------------------------------------------------------------- validation of one machine


def test_validation_finds_missing_wiring_port_clashes_and_docker_audio_on_windows(config):
    config.layout({"robot": ["brain", "tts", "speaker"]}).machine("robot", os="windows")
    config.local("tts", 'port = 7999\nruntime = "docker"')
    config.local("speaker", 'runtime = "docker"')
    errors, _ = validate_host(config.host("robot"))
    text = "\n".join(errors)
    assert "brain needs 'microphone'" in text and "brain needs 'stt'" in text
    assert "both use port 7999" in text
    assert "speaker: needs a sound device" in text


def test_services_on_other_machines_satisfy_dependencies_and_set_the_urls(config):
    config.layout(
        {"m": ["brain"], "other": ["microphone", "stt", "tts", "speaker", "ai-agent"]},
        addresses={"m": "10.0.0.1", "other": "10.0.0.2"},
    )
    host = config.host("m")
    assert validate_host(host)[0] == []
    env = resolve_env(host, "brain", None).values
    assert env["MICROPHONE_BASE_URL"] == "http://10.0.0.2:8000"
    assert env["SPEAKER_BASE_URL"] == "http://10.0.0.2:8003"
    assert env["AI_AGENT_BASE_URL"] == "http://10.0.0.2:7998"
    assert "STEPPER_BASE_URL" not in env  # optional and absent


def test_local_services_are_reached_on_localhost_and_from_containers_on_the_host_gateway(config):
    config.layout({"robot": ["brain", "microphone", "stt", "tts", "speaker"]})
    native = resolve_env(config.host("robot"), "brain", None).values
    config.local("brain", 'runtime = "docker"')
    docker = resolve_env(config.host("robot"), "brain", None).values
    assert native["STT_BASE_URL"] == "http://127.0.0.1:8001"
    assert docker["STT_BASE_URL"] == "http://host.docker.internal:8001"
    assert docker["SERVICE_HOST"] == "0.0.0.0"  # a container must listen on all interfaces


def test_brain_needs_ai_agent_but_not_the_stepper(config):
    config.layout({"robot": ["brain", "microphone", "stt", "tts", "speaker"]})
    errors, warnings = validate_host(config.host("robot"))
    assert any("brain needs 'ai-agent'" in e for e in errors)
    assert not any("stepper" in e for e in errors) and any("stepper" in w for w in warnings)


# --------------------------------------------------------------------------- environment layering


def test_env_layers_priority_and_origin(config):
    config.layout({"robot": ["stt", "tts"]}).machine("robot", workdir=config.base / "w")
    config.service("all", "[env]\nSTT_LANGUAGE = 'fr'\nLOG_LEVEL = 'WARNING'\nNOBODY_USES_THIS = 'x'\n")
    config.service("stt", "port = 9001\n[env]\nSTT_LANGUAGE = 'de'\n")
    config.local("all", "[env]\nLOG_FORMAT = 'console'\n")
    config.local("stt", "[env]\nSTT_LANGUAGE = 'en'\nOPENAI_API_KEY = 'sk-secret'\n")
    config.local("tts", "[env]\nTTS_SPEECH_RATE = 150\n")
    defaults = "STT_LANGUAGE=es\nSTT_ENGINE=local\nSERVICE_PORT=1\n# comment\nOPENAI_API_KEY=\nLOG_LEVEL=INFO\n"

    resolved = resolve_env(config.host("robot"), "stt", defaults)

    assert resolved.values["STT_LANGUAGE"] == "en" and resolved.layer_of["STT_LANGUAGE"] == "config/local/stt.toml"
    assert resolved.values["STT_ENGINE"] == "openai" and resolved.layer_of["STT_ENGINE"] == "catalogue"
    assert resolved.values["SERVICE_PORT"] == "9001" and resolved.layer_of["SERVICE_PORT"] == "computed"
    assert resolved.values["OPENAI_API_KEY"] == "sk-secret" and resolved.layer_of["OPENAI_API_KEY"] == "config/local/stt.toml"
    assert resolved.values["LOG_LEVEL"] == "WARNING" and resolved.layer_of["LOG_LEVEL"] == "config/services/all.toml"
    assert resolved.values["LOG_FORMAT"] == "console" and resolved.layer_of["LOG_FORMAT"] == "config/local/all.toml"
    assert "TTS_SPEECH_RATE" not in resolved.values  # another service's setting is never given to stt
    assert "NOBODY_USES_THIS" not in resolved.values  # all.toml only reaches the services that use a variable
    assert resolved.errors == []
    assert mask("OPENAI_API_KEY", "sk-secret") == "********" and mask("STT_LANGUAGE", "en") == "en"


def test_a_shared_setting_reaches_every_service_that_uses_it_and_no_other(config):
    config.layout({"robot": ["stt", "ai-agent", "tts"]})
    config.local("all", "[env]\nOPENAI_API_KEY = 'sk-shared'\nGROQ_API_KEY = 'gsk-agent-only'\n")
    host = config.host("robot")
    stt, agent = resolve_env(host, "stt", None).values, resolve_env(host, "ai-agent", None).values
    assert stt["OPENAI_API_KEY"] == "sk-shared" and agent["OPENAI_API_KEY"] == "sk-shared"  # both use it
    assert agent["GROQ_API_KEY"] == "gsk-agent-only" and "GROQ_API_KEY" not in stt  # only ai-agent uses it


def test_a_service_file_wins_over_all_and_local_wins_over_services(config):
    config.layout({"robot": ["tts"]})
    config.service("all", "[env]\nTTS_SPEECH_RATE = 100\n")
    config.service("tts", "[env]\nTTS_SPEECH_RATE = 120\n")
    host = config.host("robot")
    assert resolve_env(host, "tts", None).values["TTS_SPEECH_RATE"] == "120"
    config.local("all", "[env]\nTTS_SPEECH_RATE = 130\n")  # yours, shared: still below the project's own tts file
    assert resolve_env(config.host("robot"), "tts", None).values["TTS_SPEECH_RATE"] == "120"
    config.local("tts", "[env]\nTTS_SPEECH_RATE = 140\n")
    assert resolve_env(config.host("robot"), "tts", None).values["TTS_SPEECH_RATE"] == "140"


def test_required_secret_is_reported_with_the_exact_file_to_edit(config):
    config.layout({"robot": ["stt"]})
    (only,) = resolve_env(config.host("robot"), "stt", None).errors
    assert "OPENAI_API_KEY is required when STT_ENGINE=openai" in only and "config/local/stt.toml" in only

    config.env("stt", STT_ENGINE="local")
    assert resolve_env(config.host("robot"), "stt", None).errors == []  # not needed for the local engine


def test_a_setting_the_service_does_not_know_is_flagged_as_a_probable_typo(config):
    config.layout({"robot": ["stt"]}).env("stt", STT_LANGAUGE="es")
    host = config.host("robot")
    warnings = resolve_env(host, "stt", "STT_LANGUAGE=en\n").warnings
    assert any("STT_LANGAUGE" in w and "config/local/stt.toml" in w for w in warnings)
    assert resolve_env(host, "stt", None).warnings == []  # nothing to compare with before the code is fetched


def test_a_setting_that_the_tool_computes_warns_that_it_will_not_match_the_other_services(config):
    config.layout({"robot": ["stt"]}).env("stt", SERVICE_PORT=9999)
    (warning,) = [w for w in resolve_env(config.host("robot"), "stt", None).warnings if "SERVICE_PORT" in w]
    assert "computed from the layout" in warning and "config/local/stt.toml" in warning


def test_parse_env_handles_comments_quotes_and_export():
    assert parse_env("# c\nA=1\nexport B='two words'\nC=\"q\"\n\nBAD\n") == {"A": "1", "B": "two words", "C": "q"}


def test_inline_comments_are_not_part_of_the_value():
    """ai-agent's .env.example documents its settings this way; `int("6   # exchanges...")` crashed it on start."""
    text = "\n".join([
        "AI_AGENT_HISTORY_TURNS=6   # exchanges (user message + reply) remembered per session",
        "AI_AGENT_FAST_PATH_ENABLED=1  # 1 = skip project manager; 0 = always run the full pipeline",
        "LANGFUSE_HOST=             # empty = https://cloud.langfuse.com (EU)",
        "A=#not-a-value",
        "B=abc#def",
        "C='keeps # inside quotes'  # but not this",
        'D="also # kept"',
        "E='{\"stepper_1\": {\"step\": 17}}'",
    ])
    assert parse_env(text) == {
        "AI_AGENT_HISTORY_TURNS": "6",
        "AI_AGENT_FAST_PATH_ENABLED": "1",
        "LANGFUSE_HOST": "",
        "A": "",
        "B": "abc#def",
        "C": "keeps # inside quotes",
        "D": "also # kept",
        "E": '{"stepper_1": {"step": 17}}',
    }


def test_masking_hides_credentials_but_not_settings_that_merely_contain_key():
    for name in ("OPENAI_API_KEY", "GROQ_API_KEY", "LANGFUSE_SECRET_KEY", "GITHUB_PAT"):
        assert mask(name, "value") == "********", name
    for name in ("SPEAKER_DEVICE_KEYWORDS", "MICROPHONE_TARGET_KEYWORDS", "STT_LANGUAGE"):
        assert mask(name, "value") == "value", name


# --------------------------------------------------------------------------- ai-agent


def test_ai_agent_has_its_own_folder_and_reads_its_own_host_and_port_variables(config, catalogue):
    config.layout({"robot": ["ai-agent"]}).machine("robot", workdir="wd", bind="0.0.0.0")
    config.local("ai-agent", 'port = 17998\n[env]\nGROQ_URL = "https://example.invalid/v1"\n')
    host = config.host("robot")
    assert host.service_dir("ai-agent").name == "ai-agent"  # not ai-agent_microservice
    assert host.service_dir("ai-agent").parent.name == "services"
    assert catalogue.services["ai-agent"].entry == "composition_root/main.py"

    resolved = resolve_env(host, "ai-agent", None)
    assert resolved.values["AI_AGENT_HOST"] == "0.0.0.0" and resolved.values["AI_AGENT_PORT"] == "17998"
    assert "SERVICE_PORT" not in resolved.values  # ai-agent does not read it
    assert resolved.values["AI_AGENT_RELOAD"] == "0" and resolved.layer_of["AI_AGENT_RELOAD"] == "catalogue"
    assert resolved.errors == []


def test_keys_are_private_to_the_services_whose_file_holds_them(config):
    config.layout({"robot": ["ai-agent", "stt"]})
    config.env("ai-agent", GROQ_API_KEY="gsk-secret")
    config.env("stt", OPENAI_API_KEY="sk-other")
    host = config.host("robot")
    agent = resolve_env(host, "ai-agent", None)
    assert agent.values["GROQ_API_KEY"] == "gsk-secret" and agent.layer_of["GROQ_API_KEY"] == "config/local/ai-agent.toml"
    assert "OPENAI_API_KEY" not in agent.values
    assert "GROQ_API_KEY" not in resolve_env(host, "stt", None).values
    assert mask("GROQ_API_KEY", "gsk-secret") == "********"


# --------------------------------------------------------------------------- a broken file says what is wrong


def test_a_broken_settings_file_says_what_is_wrong(config):
    config.layout({"robot": ["stt"]})

    config.service("nope", "[env]\nA = 1\n")
    with pytest.raises(DeployError, match="'nope' is not a service of the catalogue"):
        config.host("robot")
    (config.paths.services / "nope.toml").unlink()

    config.local("stt", "[env\nA = 1\n")
    with pytest.raises(DeployError, match="invalid TOML"):
        config.host("robot")

    config.local("stt", "branch = 'a'\ntag = 'b'\n")
    with pytest.raises(DeployError, match="set only one of branch, tag or commit"):
        config.host("robot")

    config.local("stt", "colour = 'red'\n")
    with pytest.raises(DeployError, match="unknown key"):
        config.host("robot")

    config.local("stt", "[env]\nA = [1, 2]\n")
    with pytest.raises(DeployError, match="must be a string, a number or true/false"):
        config.host("robot")

    config.local("stt", "port = 70000\n")
    with pytest.raises(DeployError, match="port must be a number"):
        config.host("robot")

    config.local("all", "branch = 'x'\n")  # all.toml only holds [env]
    config.local("stt", "")
    with pytest.raises(DeployError, match="all.toml only has an \\[env\\] table"):
        config.host("robot")


def test_example_files_are_never_read_as_settings(config):
    config.layout({"robot": ["stt"]})
    (config.paths.local).mkdir(parents=True, exist_ok=True)
    (config.paths.local / "stt.example.toml").write_text("[env]\nOPENAI_API_KEY = 'placeholder'\n")
    assert resolve_env(config.host("robot"), "stt", None).values.get("OPENAI_API_KEY") in (None, "")


def test_a_variable_that_python_dotenv_would_expand_is_an_error(config):
    config.layout({"robot": ["tts"]}).env("tts", TTS_VOICE_NAME="a${b}")
    (error,) = resolve_env(config.host("robot"), "tts", None).errors
    assert "python-dotenv" in error
