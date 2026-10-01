"""robot.toml: ONE file of truth for the layout and for every setting and key of every service."""

from __future__ import annotations

import re
import sys
import textwrap
import tomllib
from dataclasses import replace
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import env_inventory  # noqa: E402

from oblivion import cli  # noqa: E402
from oblivion.config import DeployError, load_host, load_registry, load_topology  # noqa: E402
from oblivion.envfile import (  # noqa: E402
    LAYER_ALL, LAYER_FILE, LAYER_ROBOT, LAYER_ROBOT_ALL, SHARED_LOGGING_VARS, TUNING_VARS, is_secret, known_variables,
    mask, resolve_env,
)
from oblivion.manager import Manager  # noqa: E402
from oblivion.shell import Shell  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent
TEMPLATE = ROOT / "robot.example.toml"
needs_workspace = pytest.mark.skipif(
    not all((WORKSPACE / name).exists() for name in ("brain_microservice", "ai-agent", "stepper_microservice")),
    reason="no workspace next to this repository",
)

LAYOUT = """
[machines.pc]
address = "192.168.1.20"
services = ["microphone", "speaker"]
[machines.server]
address = "192.168.1.10"
services = ["brain", "ai-agent", "stt", "tts"]
[machines.pi]
address = "192.168.1.30"
services = ["stepper"]
"""


@pytest.fixture
def registry(tmp_path):
    return replace(load_registry(ROOT / "services.toml"), base_dir=tmp_path)


def robot(tmp_path: Path, text: str = "") -> None:
    (tmp_path / "robot.toml").write_text(LAYOUT + textwrap.dedent(text))


def machine(tmp_path, registry, name: str, text: str = ""):
    robot(tmp_path, text)
    return load_host(name, registry)


def activate(text: str) -> str:
    """The template with every commented-out variable switched on and every secret given a (dummy) value."""
    lines = [(m.group(1) if (m := re.match(r"^#([A-Z][A-Z0-9_]* = .*)$", line)) else line) for line in text.splitlines()]

    def fill(match: re.Match[str]) -> str:
        return f'{match.group(1)} = "dummy-not-a-real-secret"' if is_secret(match.group(1)) else match.group(0)

    return re.sub(r'^([A-Z][A-Z0-9_]*) = ""$', fill, "\n".join(lines), flags=re.M) + "\n"


def listed_variables(text: str) -> dict[str, set[str]]:
    """``{table: variable names}`` of the template, commented-out ones included. ``[env]`` is the table ``ALL``."""
    tables: dict[str, set[str]] = {}
    current = None
    for line in text.splitlines():
        header = re.match(r"^\[env(?:\.([a-z-]+))?\]", line)
        if header:
            current = header.group(1) or "ALL"
            tables.setdefault(current, set())
        elif current and (variable := re.match(r"^#?([A-Z][A-Z0-9_]*) = ", line)):
            tables[current].add(variable.group(1))
    return tables


# --------------------------------------------------------------------------- the template is the whole file to fill in


@needs_workspace
def test_the_committed_template_is_current():
    assert env_inventory.build() == TEMPLATE.read_text(encoding="utf-8").replace("\r\n", "\n"), (
        "run: brain_microservice/windows/Scripts/python.exe deployment/scripts/env_inventory.py --write"
    )


def test_the_template_is_valid_toml_with_the_layout_and_one_env_table_per_service():
    data = tomllib.loads(TEMPLATE.read_text(encoding="utf-8"))
    registry = load_registry(ROOT / "services.toml")
    assert set(data["machines"]) == {"pc", "server", "pi"}
    assert {k for k, v in data["env"].items() if isinstance(v, dict)} == set(registry.services)
    assert sorted(s for m in data["machines"].values() for s in m["services"]) == sorted(registry.services)
    assert set(data) == {"machines", "env"}  # nothing else to fill in, and nothing to pick a file by


@needs_workspace
def test_every_variable_a_service_reads_or_documents_is_in_the_template():
    registry = load_registry(ROOT / "services.toml")
    tables = listed_variables(TEMPLATE.read_text(encoding="utf-8"))
    missing = []
    for name, spec in registry.services.items():
        folder = WORKSPACE / spec.repo_dir
        wanted = env_inventory.code_variables(folder) | set(env_inventory.parse_example((folder / ".env.example").read_text(encoding="utf-8")))
        wanted -= SHARED_LOGGING_VARS | env_inventory.computed_variables(spec)
        wanted = {v for v in wanted if not any(fnmatchcase(v, pattern) for pattern in spec.internal)}  # never advertised
        missing += [f"[env.{name}] {v}" for v in sorted(wanted) if v not in tables[name] and v not in tables["ALL"]]
    assert missing == [], "add to scripts/env_inventory.py (EXTRA) or fix the source, then --write"
    assert SHARED_LOGGING_VARS - TUNING_VARS <= tables["ALL"]


def test_no_variable_is_listed_twice_in_the_template():
    """Replication is what the file must not have: a variable several services use is listed once, under [env]."""
    names = [v for table in listed_variables(TEMPLATE.read_text(encoding="utf-8")).values() for v in table]
    assert sorted({n for n in names if names.count(n) > 1}) == []


def test_secrets_are_listed_empty_and_nothing_real_is_in_the_template():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert re.search(r'^OPENAI_API_KEY = ""$', text, re.M) and re.search(r'^GROQ_API_KEY = ""$', text, re.M)
    assert not re.search(r"\b(sk-[A-Za-z0-9]{10,}|AIza[0-9A-Za-z_-]{20,}|gsk_[A-Za-z0-9]{10,})", text)
    for line in text.splitlines():
        if (m := re.match(r"^([A-Z][A-Z0-9_]*) = (.*)$", line)) and is_secret(m.group(1)):
            assert m.group(2) == '""', f"an active secret must be empty: {line}"


def test_only_real_secrets_get_a_dummy_value_when_the_template_is_activated():
    activated = activate(TEMPLATE.read_text(encoding="utf-8"))
    assert 'OPENAI_API_KEY = "dummy-not-a-real-secret"' in activated
    assert re.search(r'^MICROPHONE_TARGET_KEYWORDS = ""$', activated, re.M)  # KEYWORDS is a setting, not a key


# --------------------------------------------------------------------------- ...and it satisfies every service


@needs_workspace
def test_one_file_with_every_variable_satisfies_all_seven_services_on_all_three_machines(tmp_path, registry):
    """Every line switched on: no service may reject, not know, or fail to receive any of its variables."""
    (tmp_path / "robot.toml").write_text(activate(TEMPLATE.read_text(encoding="utf-8")))
    topology = load_topology(tmp_path / "robot.toml", registry)
    problems, seen = [], set()
    for machine_name in topology.machines:
        host = load_host(machine_name, registry)
        for name, instance in host.services.items():
            seen.add(name)
            example = WORKSPACE / instance.spec.repo_dir / ".env.example"
            resolved = resolve_env(host, name, example)
            problems += [f"{name}: {m}" for m in [*resolved.errors, *resolved.warnings]]
            uses, _ = known_variables(instance.spec, example)
            for variable, value in host.config.get(name, {}).items():
                if resolved.values.get(variable) != value or resolved.layer_of.get(variable) != LAYER_ROBOT:
                    problems.append(f"{name}: [env.{name}] {variable} did not arrive as {value!r}")
            for variable, value in host.config_all.items():
                own = variable in host.config.get(name, {})
                reached = resolved.layer_of.get(variable) == LAYER_ROBOT_ALL and resolved.values.get(variable) == value
                if uses(variable) and variable != "SERVICE_NAME" and not own and not reached:
                    problems.append(f"{name}: [env] {variable} did not reach a service that uses it")
                if not uses(variable) and variable in resolved.values:
                    problems.append(f"{name}: [env] {variable} reached a service that does not use it")
    assert seen == set(registry.services) and problems == []


# --------------------------------------------------------------------------- one file, many machines


def test_the_same_file_gives_each_machine_only_what_its_services_use(tmp_path, registry):
    text = """
        [env]
        LOG_LEVEL = "DEBUG"
        OPENAI_API_KEY = "shared-key-not-real"
        [env.ai-agent]
        GROQ_API_KEY = "agent-key-not-real"
        [env.stepper]
        MOCK_HARDWARE = 0
        [env.microphone]
        MICROPHONE_TARGET_KEYWORDS = "usb"
    """
    pc, server, pi = (machine(tmp_path, registry, m, text) for m in ("pc", "server", "pi"))
    assert set(pc.config) == {"microphone"} and set(pi.config) == {"stepper"}  # only its own services' tables
    mic = resolve_env(pc, "microphone", None).values
    assert mic["LOG_LEVEL"] == "DEBUG" and mic["MICROPHONE_TARGET_KEYWORDS"] == "usb"
    assert "OPENAI_API_KEY" not in mic and "GROQ_API_KEY" not in mic  # the PC's services never see a key they cannot use
    assert resolve_env(pi, "stepper", None).values["MOCK_HARDWARE"] == "0"
    assert resolve_env(server, "stt", None).values["OPENAI_API_KEY"] == "shared-key-not-real"
    assert resolve_env(server, "ai-agent", None).values["GROQ_API_KEY"] == "agent-key-not-real"
    assert "GROQ_API_KEY" not in resolve_env(server, "stt", None).values


def test_a_value_may_be_a_string_a_number_or_a_boolean(tmp_path, registry):
    server = machine(tmp_path, registry, "server", """
        [env.brain]
        STARTUP_PREFLIGHT_TIMEOUT_SECONDS = 90
        STARTUP_PREFLIGHT_ENABLED = false
        STEPPER_DEFAULT_RPM = 12.5
        PROVIDER_NAME = "local"
    """)
    assert server.config["brain"] == {
        "STARTUP_PREFLIGHT_TIMEOUT_SECONDS": "90", "STARTUP_PREFLIGHT_ENABLED": "false",
        "STEPPER_DEFAULT_RPM": "12.5", "PROVIDER_NAME": "local",
    }


@pytest.mark.parametrize("body,message", [
    ("[env.brian]\nX = 1\n", r"\[env.brian\] is not a service of the catalogue"),
    ('[env.brain]\nX = ["a"]\n', "must be a string, a number or true/false, not list"),
    ('[env]\nX = { a = 1 }\n', r"\[env.X\] is not a service"),
])
def test_a_wrong_env_table_says_what_is_wrong(tmp_path, registry, body, message):
    robot(tmp_path, body)
    with pytest.raises(DeployError, match=message):
        load_topology(tmp_path / "robot.toml", registry)


# --------------------------------------------------------------------------- the layers


def test_the_robot_file_is_a_layer_between_the_defaults_and_the_machine_local_overlay(tmp_path, registry):
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hosts" / "server.toml").write_text(textwrap.dedent("""
        [host]
        machine = "server"
        env_file = "machine.env"
        [services.tts]
        [services.tts.env]
        TTS_SPEECH_RATE = "from-host"
        LOG_FORMAT = "from-host"
    """))
    (tmp_path / "machine.env").write_text("TTS__TTS_VOICE_NAME=from-env-file\nALL__LOG_OUTPUT=from-env-file-all\nTTS__LOG_LEVEL=from-env-file\n")
    robot(tmp_path, """
        [env]
        LOG_LEVEL = "robot-all"
        LOG_FORMAT = "robot-all"
        LOG_OUTPUT = "robot-all"
        TTS_SPEECH_RATE = "robot-all"
        [env.tts]
        TTS_SPEECH_RATE = "robot-service"
        TTS_VOICE_NAME = "robot-service"
        LOG_LEVEL = "robot-service"
    """)
    resolved = resolve_env(load_host("server", registry), "tts", None)
    got = {k: (resolved.values[k], resolved.layer_of[k]) for k in ("LOG_LEVEL", "LOG_FORMAT", "LOG_OUTPUT", "TTS_SPEECH_RATE", "TTS_VOICE_NAME")}
    assert got == {
        "LOG_LEVEL": ("from-env-file", LAYER_FILE),  # the machine-local overlay beats the robot file
        "LOG_FORMAT": ("from-host", "host"),  # a host file beats [env]
        "LOG_OUTPUT": ("from-env-file-all", LAYER_ALL),  # ALL__ of the overlay beats [env]
        "TTS_SPEECH_RATE": ("robot-service", LAYER_ROBOT),  # [env.tts] beats the host file and [env]
        "TTS_VOICE_NAME": ("from-env-file", LAYER_FILE),
    }
    assert resolve_env(load_host("server", registry), "tts", None).layer_of["LOG_FORMAT"] == "host"


def test_env_reaches_only_services_that_use_the_variable_and_a_service_table_beats_it(tmp_path, registry):
    server = machine(tmp_path, registry, "server", """
        [env]
        OPENAI_API_KEY = "for-all-not-real"
        [env.ai-agent]
        OPENAI_API_KEY = "for-the-agent-not-real"
    """)
    stt, agent = resolve_env(server, "stt", None), resolve_env(server, "ai-agent", None)
    assert (stt.values["OPENAI_API_KEY"], stt.layer_of["OPENAI_API_KEY"]) == ("for-all-not-real", LAYER_ROBOT_ALL)
    assert (agent.values["OPENAI_API_KEY"], agent.layer_of["OPENAI_API_KEY"]) == ("for-the-agent-not-real", LAYER_ROBOT)


# --------------------------------------------------------------------------- mistakes are reported where they are made


def test_a_variable_the_service_does_not_know_is_flagged_naming_the_robot_file(tmp_path, registry):
    example = tmp_path / ".env.example"
    example.write_text("STT_ENGINE=openai\nSTT_LANGUAGE=en\n")
    server = machine(tmp_path, registry, "server", """
        [env.stt]
        STT_LANGUAGE = "es"
        STT_LANGUEGE = "typo"
    """)
    (warning,) = resolve_env(server, "stt", example).warnings
    assert "STT_LANGUEGE is set in robot.toml" in warning and "typo" in warning


def test_a_computed_variable_set_in_the_robot_file_is_warned_about(tmp_path, registry):
    server = machine(tmp_path, registry, "server", """
        [env.brain]
        STT_BASE_URL = "http://elsewhere:9"
        [env.stt]
        SERVICE_PORT = 9
    """)
    brain, stt = resolve_env(server, "brain", None), resolve_env(server, "stt", None)
    assert any("STT_BASE_URL is computed from robot.toml" in w for w in brain.warnings)
    assert any("SERVICE_PORT is computed from robot.toml" in w for w in stt.warnings)


def test_a_missing_key_says_where_to_put_it_in_the_robot_file(tmp_path, registry):
    server = machine(tmp_path, registry, "server")
    (error,) = resolve_env(server, "stt", None).errors
    assert 'OPENAI_API_KEY is required when STT_ENGINE=openai; put OPENAI_API_KEY = "..." under [env.stt]' in error
    assert "in robot.toml" in error
    errors, _ = Manager(Shell(dry_run=True), server, registry).validate(["stt"])
    assert any("[env.stt]" in e for e in errors)
    filled = machine(tmp_path, registry, "server", '[env]\nOPENAI_API_KEY = "key-not-real"\n')
    assert resolve_env(filled, "stt", None).errors == []


def test_a_key_in_the_robot_file_is_masked_in_plan_and_env_output(tmp_path, registry, capsys):
    robot(tmp_path, '[env]\nOPENAI_API_KEY = "sk-not-a-real-key"\n')
    assert cli.main(["env", "stt", "--host", "server", "--robot", str(tmp_path / "robot.toml")]) in (0, 1)
    out = capsys.readouterr().out
    assert "OPENAI_API_KEY=********    # robot ALL" in out and "sk-not-a-real-key" not in out
    assert mask("OPENAI_API_KEY", "sk-not-a-real-key") == "********"


def test_the_generated_env_of_a_service_carries_the_robot_files_values(tmp_path, registry):
    server = machine(tmp_path, registry, "server", '[env]\nLOG_LEVEL = "DEBUG"\n[env.stt]\nSTT_LANGUAGE = "es"\nOPENAI_API_KEY = "key-not-real"\n')
    server = replace(server, workdir=tmp_path / "work")
    Manager(Shell(echo=False), server, registry).write_env("stt")
    env = (tmp_path / "work" / "services" / "stt_microservice" / ".env").read_text()
    assert "LOG_LEVEL=DEBUG\n" in env and "STT_LANGUAGE=es\n" in env and "OPENAI_API_KEY=key-not-real\n" in env
    assert "SERVICE_PORT=8001\n" in env  # ...next to the port derived from the catalogue


# --------------------------------------------------------------------------- the file's name


def test_the_robot_file_is_never_committed_but_its_template_is():
    ignored = [line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
    assert "/robot.toml" in ignored and "robot.example.toml" not in ignored
    assert "secrets/*" in ignored  # the machine-local overlay stays out of git too


def test_the_commands_take_the_robot_file_with_robot(tmp_path, capsys):
    robot(tmp_path)
    assert cli.main(["topology", "--robot", str(tmp_path / "robot.toml")]) == 0
    assert "3 machines" in capsys.readouterr().out
