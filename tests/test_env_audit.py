"""Environment variables of every service versus what the deploy tool sets, masks, warns about and documents."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from oblivion.config import load_host, load_registry
from oblivion.envfile import SHARED_LOGGING_VARS, is_secret, parse_env, resolve_env
from oblivion.manager import Manager
from oblivion.shell import Shell

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent
FOLDERS = {
    "brain": "brain_microservice", "microphone": "microphone_microservice", "stt": "stt_microservice",
    "tts": "tts_microservice", "speaker": "speaker_microservice", "stepper": "stepper_microservice",
    "ai-agent": "ai-agent",
}


@pytest.fixture(scope="module")
def registry():
    return load_registry(ROOT / "services.toml")


def host_for(tmp_path: Path, registry, body: str):
    path = tmp_path / "h.toml"
    path.write_text(textwrap.dedent(body).replace("WORKDIR", (tmp_path / "work").as_posix()))
    return load_host(str(path), registry)


# --------------------------------------------------------------------------- values


def test_the_stepper_mock_is_selected_with_the_only_value_the_stepper_understands(registry):
    """The stepper does `os.getenv("MOCK_HARDWARE", "0") == "1"`: "true" selects the REAL motor driver on a Pi."""
    assert registry.services["stepper"].env["MOCK_HARDWARE"] == "1"
    template = (ROOT / "robot.example.toml").read_text(encoding="utf-8")
    assert "#MOCK_HARDWARE = 1" in template  # the safe default, listed under [env.stepper]
    assert "MOCK_HARDWARE = 0 under [env.stepper] for real motors" in template  # how the Pi's owner switches the driver on


def test_variables_every_service_reads_through_shared_logging_are_never_flagged_as_typos(registry, tmp_path):
    documented = tmp_path / ".env.example"
    documented.write_text("SERVICE_PORT=1\n")
    settings = "\n".join(f'{name} = "x"' for name in sorted(SHARED_LOGGING_VARS - {"SERVICE_NAME"}))
    host = host_for(tmp_path, registry, f"[host]\nworkdir = \"WORKDIR\"\n[services.tts]\n[services.tts.env]\n{settings}\nTTS_SPEECH_RATTE = \"1\"\n")
    warnings = resolve_env(host, "tts", documented).warnings
    assert len(warnings) == 1 and "TTS_SPEECH_RATTE" in warnings[0]  # a real typo is still caught


def test_credentials_are_masked_including_the_trace_export_headers_but_settings_are_not():
    for key in ("OPENAI_API_KEY", "GITHUB_PAT", "LANGFUSE_SECRET_KEY", "TRACE_EXPORT_HEADERS", "GITHUB_API_KEY"):
        assert is_secret(key), key
    for key in ("MICROPHONE_TARGET_KEYWORDS", "SPEAKER_DEVICE_KEYWORDS", "TRACE_EXPORT_URL", "STEPPER_CONFIGS", "LOG_FORMAT"):
        assert not is_secret(key), key


def test_a_github_key_under_its_alias_counts_as_an_llm_provider(registry, tmp_path):
    secrets = tmp_path / "s.env"
    secrets.write_text("AI_AGENT__GITHUB_API_KEY=not-a-real-key\n")
    host = host_for(tmp_path, registry, f'[host]\nsecrets = "{secrets.as_posix()}"\n[services.ai-agent]\n')
    assert resolve_env(host, "ai-agent", None).warnings == []


# --------------------------------------------------------------------------- Brain and the stepper agree


def stepper_manager(tmp_path: Path, registry, stepper_example: str | None, brain_example: str = "", host_env: str = ""):
    host = host_for(tmp_path, registry, f"""
        [host]
        workdir = "WORKDIR"
        [services.stepper]
        [services.stepper.env]
        {host_env}
        [services.brain]
        [remote]
        microphone = "http://mic:8000"
        stt = "http://stt:8001"
        tts = "http://tts:8002"
        speaker = "http://spk:8003"
        ai-agent = "http://ai:7998"
    """)
    for name, text in (("stepper", stepper_example), ("brain", brain_example)):
        if text is not None:
            folder = host.service_dir(name)
            folder.mkdir(parents=True)
            (folder / ".env.example").write_text(text)
    return Manager(Shell(dry_run=True), host, registry)


TWO = "STEPPER_CONFIGS='{\"stepper_1\": {\"step\": 17, \"dir\": 27, \"en\": 5}, \"stepper_2\": {\"step\": 23, \"dir\": 24, \"en\": 25}}'\n"
ARMS = "STEPPER_LEFT_ARM_STEPPER_ID=stepper_1\nSTEPPER_RIGHT_ARM_STEPPER_ID=stepper_2\n"


def test_arms_that_match_the_steppers_of_this_machine_are_fine(tmp_path, registry):
    assert stepper_manager(tmp_path, registry, TWO, ARMS)._stepper_problems() == []


def test_an_arm_pointing_at_a_stepper_that_does_not_exist_is_an_error(tmp_path, registry):
    brain = "STEPPER_LEFT_ARM_STEPPER_ID=stepper_1\nSTEPPER_RIGHT_ARM_STEPPER_ID=stepper_3\n"
    (problem,) = stepper_manager(tmp_path, registry, TWO, brain)._stepper_problems()
    assert "STEPPER_RIGHT_ARM_STEPPER_ID=stepper_3" in problem and "stepper_1, stepper_2" in problem


def test_the_host_file_can_rename_the_steppers_and_the_check_follows(tmp_path, registry):
    one = "STEPPER_CONFIGS = '{\"left\": {\"step\": 1, \"dir\": 2, \"en\": 3}}'"
    problems = stepper_manager(tmp_path, registry, TWO, ARMS, host_env=one)._stepper_problems()
    assert len(problems) == 2 and all("left" in p for p in problems)


@pytest.mark.parametrize("value", ["not json", "[]", "{}", '{"a": {"step": 1, "dir": 2}}', '{"a": {"step": "17", "dir": 2, "en": 3}}'])
def test_a_stepper_configuration_the_stepper_could_not_start_with_is_an_error(tmp_path, registry, value):
    (problem,) = stepper_manager(tmp_path, registry, f"STEPPER_CONFIGS='{value}'\n")._stepper_problems()
    assert "STEPPER_CONFIGS is invalid" in problem


def test_nothing_is_checked_before_the_code_was_fetched_or_when_the_stepper_is_elsewhere(tmp_path, registry):
    assert stepper_manager(tmp_path, registry, None)._stepper_problems() == []
    remote_only = host_for(tmp_path, registry, '[host]\nworkdir = "WORKDIR"\n[services.brain]\n')
    assert Manager(Shell(dry_run=True), remote_only, registry)._stepper_problems() == []


def test_validate_reports_the_stepper_wiring(tmp_path, registry):
    brain = "STEPPER_LEFT_ARM_STEPPER_ID=nope\n"
    errors, _ = stepper_manager(tmp_path, registry, TWO, brain).validate(["stepper", "brain"])
    assert any("STEPPER_LEFT_ARM_STEPPER_ID=nope" in e for e in errors)


# --------------------------------------------------------------------------- the manual follows the services


@pytest.mark.parametrize("service", sorted(FOLDERS))
def test_every_variable_a_service_documents_in_its_env_example_appears_in_the_manual(service):
    example = WORKSPACE / FOLDERS[service] / ".env.example"
    if not example.exists():
        pytest.skip("no workspace next to this repository")
    manual = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    # Brain's route settings are listed as one group (`*_ENDPOINT`); VSCODE_* and RUN_LIVE_* are for development.
    exempt = ("VSCODE_", "RUN_LIVE_")
    missing = [
        key for key in parse_env(example.read_text(encoding="utf-8"))
        if key not in manual and not key.endswith("_ENDPOINT") and not key.startswith(exempt)
    ]
    assert missing == [], f"{service}: add to docs/DEPLOYMENT.md section 5.3"
