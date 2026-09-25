"""Host files, validation and environment layering: no network, no processes."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from oblivion.config import DeployError, apply_branch_overrides, load_host, load_registry, validate_host
from oblivion.envfile import mask, parse_env, resolve_env

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def registry():
    return load_registry(ROOT / "services.toml")


def host_file(tmp_path: Path, body: str) -> str:
    path = tmp_path / "h.toml"
    path.write_text(textwrap.dedent(body))
    return str(path)


def test_the_shipped_registry_and_examples_are_valid(registry):
    assert {"brain", "microphone", "stt", "tts", "speaker", "stepper", "ai-agent"} <= set(registry.services)
    for example in (ROOT / "hosts").glob("*.example.toml"):
        errors, _ = validate_host(load_host(str(example), registry))
        assert errors == [], f"{example.name}: {errors}"


def test_defaults_branch_and_per_service_branch_and_cli_override(registry, tmp_path):
    host = load_host(host_file(tmp_path, """
        [defaults]
        branch = "feature_x"
        [services.stt]
        [services.tts]
        branch = "hotfix"
    """), registry)
    assert (host.services["stt"].branch, host.services["tts"].branch) == ("feature_x", "hotfix")

    every = apply_branch_overrides(host, ["candidate"])
    assert {i.branch for i in every.services.values()} == {"candidate"}
    one = apply_branch_overrides(host, ["stt=abc123"])
    assert (one.services["stt"].branch, one.services["tts"].branch) == ("abc123", "hotfix")
    with pytest.raises(DeployError, match="not deployed"):
        apply_branch_overrides(host, ["brain=x"])


def test_validation_finds_missing_wiring_port_clashes_and_docker_audio_on_windows(registry, tmp_path):
    host = load_host(host_file(tmp_path, """
        [host]
        os = "windows"
        [services.brain]
        [services.tts]
        port = 7999
        runtime = "docker"
        [services.speaker]
        runtime = "docker"
    """), registry)
    errors, _ = validate_host(host)
    text = "\n".join(errors)
    assert "brain needs 'microphone'" in text and "brain needs 'stt'" in text
    assert "both use port 7999" in text
    assert "speaker: needs a sound device" in text


def test_remote_services_satisfy_dependencies_and_set_the_urls(registry, tmp_path):
    host = load_host(host_file(tmp_path, """
        [services.brain]
        [remote]
        microphone = "http://10.0.0.2:8000/"
        stt = "http://10.0.0.3:8001"
        tts = "http://10.0.0.3:8002"
        speaker = "http://10.0.0.2:8003"
        ai-agent = "http://10.0.0.4:7998"
    """), registry)
    assert validate_host(host)[0] == []
    env = resolve_env(host, "brain", None).values
    assert env["MICROPHONE_BASE_URL"] == "http://10.0.0.2:8000"  # trailing slash stripped
    assert env["SPEAKER_BASE_URL"] == "http://10.0.0.2:8003"
    assert env["AI_AGENT_BASE_URL"] == "http://10.0.0.4:7998"
    assert "STEPPER_BASE_URL" not in env  # optional and absent


def test_local_services_are_reached_on_localhost_and_from_containers_on_the_host_gateway(registry, tmp_path):
    body = """
        [services.brain]
        runtime = "%s"
        [services.microphone]
        [services.stt]
        [services.tts]
        [services.speaker]
    """
    native = resolve_env(load_host(host_file(tmp_path, body % "native"), registry), "brain", None).values
    docker = resolve_env(load_host(host_file(tmp_path, body % "docker"), registry), "brain", None).values
    assert native["STT_BASE_URL"] == "http://127.0.0.1:8001"
    assert docker["STT_BASE_URL"] == "http://host.docker.internal:8001"
    assert docker["SERVICE_HOST"] == "0.0.0.0"  # a container must listen on all interfaces


def test_env_layers_priority_and_origin(registry, tmp_path):
    defaults = tmp_path / ".env.example"
    defaults.write_text("STT_LANGUAGE=es\nSTT_ENGINE=local\nSERVICE_PORT=1\n# comment\nOPENAI_API_KEY=\n")
    secrets = tmp_path / "s.env"
    secrets.write_text("STT__OPENAI_API_KEY=sk-secret\nTTS__OTHER=x\nnot_namespaced=1\n")
    host = load_host(host_file(tmp_path, f"""
        [host]
        secrets = "{secrets.as_posix()}"
        [services.stt]
        port = 9001
        [services.stt.env]
        STT_LANGUAGE = "en"
    """), registry)

    resolved = resolve_env(host, "stt", defaults)

    assert resolved.values["STT_LANGUAGE"] == "en" and resolved.layer_of["STT_LANGUAGE"] == "host"
    assert resolved.values["STT_ENGINE"] == "openai" and resolved.layer_of["STT_ENGINE"] == "registry"
    assert resolved.values["SERVICE_PORT"] == "9001" and resolved.layer_of["SERVICE_PORT"] == "computed"
    assert resolved.values["OPENAI_API_KEY"] == "sk-secret" and resolved.layer_of["OPENAI_API_KEY"] == "secrets"
    assert "OTHER" not in resolved.values  # another service's secret is never given to stt
    assert resolved.errors == []
    assert mask("OPENAI_API_KEY", "sk-secret") == "********" and mask("STT_LANGUAGE", "en") == "en"


def test_required_secret_is_reported_with_the_exact_line_to_add(registry, tmp_path):
    host = load_host(host_file(tmp_path, "[services.stt]\n"), registry)
    (only,) = resolve_env(host, "stt", None).errors
    assert "OPENAI_API_KEY is required when STT_ENGINE=openai" in only and "STT__OPENAI_API_KEY" in only

    local = load_host(host_file(tmp_path, '[services.stt]\n[services.stt.env]\nSTT_ENGINE = "local"\n'), registry)
    assert resolve_env(local, "stt", None).errors == []  # not needed for the local engine


def test_a_setting_the_service_does_not_know_is_flagged_as_a_probable_typo(registry, tmp_path):
    defaults = tmp_path / ".env.example"
    defaults.write_text("STT_LANGUAGE=en\n")
    host = load_host(host_file(tmp_path, '[services.stt]\n[services.stt.env]\nSTT_LANGAUGE = "es"\n'), registry)
    assert any("STT_LANGAUGE" in w for w in resolve_env(host, "stt", defaults).warnings)
    assert resolve_env(host, "stt", None).warnings == []  # nothing to compare with before the code is fetched


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


def test_a_broken_host_file_says_what_is_wrong(registry, tmp_path):
    with pytest.raises(DeployError, match="unknown service 'nope'"):
        load_host(host_file(tmp_path, "[services.nope]\n"), registry)
    with pytest.raises(DeployError, match="invalid TOML"):
        load_host(host_file(tmp_path, "[services.stt"), registry)
    with pytest.raises(DeployError, match="file not found"):
        load_host(str(tmp_path / "missing.toml"), registry)


def test_masking_hides_credentials_but_not_settings_that_merely_contain_key(registry):
    for name in ("OPENAI_API_KEY", "GROQ_API_KEY", "LANGFUSE_SECRET_KEY", "GITHUB_PAT"):
        assert mask(name, "value") == "********", name
    for name in ("SPEAKER_DEVICE_KEYWORDS", "MICROPHONE_TARGET_KEYWORDS", "STT_LANGUAGE"):
        assert mask(name, "value") == "value", name


def test_brain_needs_ai_agent_but_not_the_stepper(registry, tmp_path):
    host = load_host(host_file(tmp_path, """
        [services.brain]
        [services.microphone]
        [services.stt]
        [services.tts]
        [services.speaker]
    """), registry)
    errors, warnings = validate_host(host)
    assert any("brain needs 'ai-agent'" in e for e in errors)
    assert not any("stepper" in e for e in errors) and any("stepper" in w for w in warnings)


def test_ai_agent_has_its_own_folder_and_reads_its_own_host_and_port_variables(registry, tmp_path):
    host = load_host(host_file(tmp_path, """
        [host]
        workdir = "wd"
        bind = "0.0.0.0"
        [services.ai-agent]
        port = 17998
        [services.ai-agent.env]
        GROQ_URL = "https://example.invalid/v1"
    """), registry)
    assert host.service_dir("ai-agent").name == "ai-agent"  # not ai-agent_microservice
    assert host.service_dir("ai-agent").parent.name == "services"
    assert registry.services["ai-agent"].entry == "composition_root/main.py"

    resolved = resolve_env(host, "ai-agent", None)
    assert resolved.values["AI_AGENT_HOST"] == "0.0.0.0" and resolved.values["AI_AGENT_PORT"] == "17998"
    assert "SERVICE_PORT" not in resolved.values  # ai-agent does not read it
    assert resolved.values["AI_AGENT_RELOAD"] == "0" and resolved.layer_of["AI_AGENT_RELOAD"] == "registry"
    assert resolved.errors == []


def test_ai_agent_secrets_are_namespaced_with_an_underscore_and_never_leak_to_other_services(registry, tmp_path):
    secrets = tmp_path / "s.env"
    secrets.write_text("AI_AGENT__GROQ_API_KEY=gsk-secret\nSTT__OPENAI_API_KEY=sk-other\n")
    host = load_host(host_file(tmp_path, f"""
        [host]
        secrets = "{secrets.as_posix()}"
        [services.ai-agent]
        [services.stt]
    """), registry)
    agent = resolve_env(host, "ai-agent", None)
    assert agent.values["GROQ_API_KEY"] == "gsk-secret" and agent.layer_of["GROQ_API_KEY"] == "secrets"
    assert "OPENAI_API_KEY" not in agent.values
    assert "GROQ_API_KEY" not in resolve_env(host, "stt", None).values
    assert mask("GROQ_API_KEY", "gsk-secret") == "********"


def test_a_host_file_can_point_one_service_at_another_git_source(registry, tmp_path):
    host = load_host(host_file(tmp_path, f"""
        [services.stt]
        git = "{tmp_path.as_posix()}/my_stt"
        [services.tts]
    """), registry)
    assert host.services["stt"].spec.git == f"{tmp_path.as_posix()}/my_stt"
    assert host.services["tts"].spec.git == registry.services["tts"].git  # the others keep the catalogue's
    assert registry.services["stt"].git != host.services["stt"].spec.git  # the catalogue itself is untouched
    assert apply_branch_overrides(host, ["stt=x"]).services["stt"].spec.git == host.services["stt"].spec.git
