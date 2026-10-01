"""The machine env file, the optional machine-local overlay of robot.toml: ALL__ / SERVICE__ lines and their checks."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from oblivion.config import load_host, load_registry  # noqa: E402
from oblivion.envfile import LAYER_ALL, LAYER_FILE, check_env_file, resolve_env  # noqa: E402
from oblivion.manager import Manager  # noqa: E402
from oblivion.shell import Shell  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def registry():
    return load_registry(ROOT / "services.toml")


def host_for(tmp_path: Path, registry, body: str, env_text: str | None = None, key: str = "env_file"):
    path = tmp_path / "h.toml"
    lines = [f'[host]\nworkdir = "{(tmp_path / "work").as_posix()}"\n']
    if env_text is not None:
        (tmp_path / "machine.env").write_text(env_text)
        lines.append(f'{key} = "{(tmp_path / "machine.env").as_posix()}"\n')
    path.write_text("".join(lines) + textwrap.dedent(body))
    return load_host(str(path), registry)


def test_one_file_serves_many_machines_and_gives_each_service_only_its_own_lines(registry, tmp_path):
    text = textwrap.dedent("""
        ALL__LOG_LEVEL=DEBUG
        STT__OPENAI_API_KEY=stt-key-not-real
        AI_AGENT__GROQ_API_KEY=agent-key-not-real
        MICROPHONE__MICROPHONE_TARGET_KEYWORDS=usb
        SPEAKER__SPEAKER_DEVICE_KEYWORDS=speakers
    """)
    pc = host_for(tmp_path, registry, "[services.microphone]\n[services.speaker]\n", env_text=text)
    for name in ("microphone", "speaker"):
        values = resolve_env(pc, name, None).values
        assert values["LOG_LEVEL"] == "DEBUG"
        assert "OPENAI_API_KEY" not in values and "GROQ_API_KEY" not in values, f"{name} was handed another service's key"
    assert resolve_env(pc, "microphone", None).values["MICROPHONE_TARGET_KEYWORDS"] == "usb"
    assert "SPEAKER_DEVICE_KEYWORDS" not in resolve_env(pc, "microphone", None).values
    assert resolve_env(pc, "speaker", None).values["SPEAKER_DEVICE_KEYWORDS"] == "speakers"


# --------------------------------------------------------------------------- ALL__ and the layers


def test_all_sets_a_shared_setting_for_every_service_and_a_service_line_or_the_host_file_beats_it(registry, tmp_path):
    host = host_for(tmp_path, registry, """
        [services.tts]
        [services.speaker]
        [services.speaker.env]
        LOG_LEVEL = "WARNING"
        [services.stt]
    """, env_text="ALL__LOG_LEVEL=DEBUG\nSTT__LOG_LEVEL=ERROR\nALL__LOG_FORMAT=console\n")
    tts, speaker, stt = (resolve_env(host, n, None) for n in ("tts", "speaker", "stt"))
    assert (tts.values["LOG_LEVEL"], tts.layer_of["LOG_LEVEL"]) == ("DEBUG", LAYER_ALL)
    assert (speaker.values["LOG_LEVEL"], speaker.layer_of["LOG_LEVEL"]) == ("WARNING", "host")  # more specific than ALL
    assert (stt.values["LOG_LEVEL"], stt.layer_of["LOG_LEVEL"]) == ("ERROR", LAYER_FILE)  # the service's own line wins
    assert all(r.values["LOG_FORMAT"] == "console" for r in (tts, speaker, stt))


def test_all_gives_one_value_to_every_service_that_uses_the_variable_and_to_no_other(registry, tmp_path):
    """One OPENAI_API_KEY line serves STT and ai-agent; the microphone, which has no such setting, never sees it."""
    host = host_for(tmp_path, registry, "[services.stt]\n[services.ai-agent]\n[services.microphone]\n[services.tts]\n",
                    env_text="ALL__OPENAI_API_KEY=key-not-real\nAI_AGENT__OPENAI_API_KEY=agent-only-key-not-real\n")
    stt, agent, mic, tts = (resolve_env(host, n, None) for n in ("stt", "ai-agent", "microphone", "tts"))
    assert (stt.values["OPENAI_API_KEY"], stt.layer_of["OPENAI_API_KEY"]) == ("key-not-real", LAYER_ALL)
    assert agent.values["OPENAI_API_KEY"] == "agent-only-key-not-real"  # a service's own line wins
    assert "OPENAI_API_KEY" not in mic.values and "OPENAI_API_KEY" not in tts.values, "a key reached a service that has no use for it"
    assert stt.errors == []  # ...and it satisfies STT's required key


def test_all_never_carries_what_differs_per_service_or_the_tool_computes(registry, tmp_path):
    host = host_for(tmp_path, registry, "[services.stt]\n", env_text="ALL__SERVICE_NAME=x\nALL__SERVICE_PORT=9\n")
    values = resolve_env(host, "stt", None).values
    assert values["SERVICE_PORT"] == "8001" and "SERVICE_NAME" not in values
    warnings = check_env_file(host, registry.services)
    assert len(warnings) == 2 and all("is ignored" in w for w in warnings)


def test_an_all_variable_no_service_uses_is_flagged_once_every_example_was_seen(registry, tmp_path):
    examples = {}
    for name in registry.services:
        example = tmp_path / f"{name}.env.example"
        example.write_text("SOME_SETTING=1\n")
        examples[name] = example
    host = host_for(tmp_path, registry, "[services.stt]\n", env_text="ALL__SOME_SETTING=1\nALL__SOME_SETTNG=1\nALL__LOG_LEVEL=DEBUG\n")
    (warning,) = check_env_file(host, registry.services, examples)
    assert "SOME_SETTNG" in warning and "typo" in warning
    assert check_env_file(host, registry.services) == []  # without the examples it cannot tell, so it stays quiet


def test_the_older_secrets_key_still_names_the_machine_env_file(registry, tmp_path):
    host = host_for(tmp_path, registry, "[services.stt]\n", env_text="STT__OPENAI_API_KEY=key-not-real\n", key="secrets")
    assert host.env_file is not None and resolve_env(host, "stt", None).values["OPENAI_API_KEY"] == "key-not-real"


# --------------------------------------------------------------------------- mistakes are reported


def test_lines_that_nothing_reads_are_reported_with_the_line_number(registry, tmp_path):
    host = host_for(tmp_path, registry, "[services.stt]\n", env_text=textwrap.dedent("""\
        # a comment
        OPENAI_API_KEY=no-prefix
        STTT__OPENAI_API_KEY=typo-in-the-service
        STT__LANGUAGE
        STT__STT_LANGUAGE=en
        STT__STT_LANGUAGE=es
    """))
    text = "\n".join(check_env_file(host, registry.services))
    assert "line 2" in text and "no SERVICE__ prefix" in text
    assert "line 3" in text and "'STTT' is not a service" in text
    assert "line 4" in text and "not NAME=value" in text
    assert "line 6" in text and "set twice" in text


def test_a_missing_machine_env_file_is_reported_not_silently_ignored(registry, tmp_path):
    host = host_for(tmp_path, registry, "[services.stt]\n", env_text="")
    host.env_file.unlink()
    (warning,) = check_env_file(host, {"stt": registry.services["stt"]})
    assert "does not exist" in warning


def test_a_variable_the_service_does_not_know_is_flagged_but_the_ones_its_code_reads_are_not(registry, tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("# AI_AGENT_HOST=0.0.0.0\nAI_AGENT_PORT=7998\nGROQ_API_KEY=\n")
    host = host_for(tmp_path, registry, "[services.ai-agent]\n", env_text=textwrap.dedent("""\
        AI_AGENT__GROQ_API_KEY=key-not-real
        AI_AGENT__AI_AGENT_MODEL_PHASE_3=some-model
        AI_AGENT__AI_AGENT_MODELS_FILE=other.json
        AI_AGENT__GITHUB_API_KEY=alias-not-real
        AI_AGENT__GROQ_API_KYE=typo
    """))
    (warning,) = resolve_env(host, "ai-agent", example).warnings
    assert "GROQ_API_KYE" in warning and "typo" in warning


def test_a_computed_variable_set_in_the_env_file_is_warned_about(registry, tmp_path):
    host = host_for(tmp_path, registry, "[services.brain]\n[services.stt]\n", env_text="BRAIN__STT_BASE_URL=http://elsewhere:9\nSTT__SERVICE_PORT=9\n")
    brain, stt = resolve_env(host, "brain", None), resolve_env(host, "stt", None)
    assert any("STT_BASE_URL is computed from the host file" in w for w in brain.warnings)
    assert any("SERVICE_PORT is computed from the host file" in w for w in stt.warnings)


def test_validate_reports_the_env_file_problems(registry, tmp_path):
    host = host_for(tmp_path, registry, "[services.stt]\n", env_text="OPENAI_API_KEY=wrong-place\n")
    errors, warnings = Manager(Shell(dry_run=True), host, registry).validate(None)
    assert any("no SERVICE__ prefix" in w for w in warnings)
    assert any("OPENAI_API_KEY is required" in e for e in errors)  # ...and so the key really is missing


def test_the_all_in_one_example_points_at_a_machine_env_file():
    registry = load_registry(ROOT / "services.toml")
    host = load_host(str(ROOT / "hosts" / "all-in-one.example.toml"), registry)
    assert host.env_file is not None and host.env_file.name == "all-in-one.env"


def test_filling_in_a_templates_empty_placeholder_by_appending_is_not_a_duplicate(registry, tmp_path):
    host = host_for(tmp_path, registry, "[services.stt]\n", env_text="STT__OPENAI_API_KEY=\nSTT__OPENAI_API_KEY=key-not-real\n")
    assert check_env_file(host, {"stt": registry.services["stt"]}) == []
