"""Environment variables of every service versus what the deploy tool sets, masks, warns about and documents."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import Config

from composition_root.container import new_deployment_service
from domain.rules.dotenv import parse_env
from domain.rules.env_names import SHARED_LOGGING_VARS, is_secret
from domain.rules.env_resolution import resolve_env
from infrastructure.outbound.shell.shell import Shell

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent
FOLDERS = {
    "brain": "brain_microservice", "microphone": "microphone_microservice", "stt": "stt_microservice",
    "tts": "tts_microservice", "speaker": "speaker_microservice", "stepper": "stepper_microservice",
    "ai-agent": "ai-agent",
}


# --------------------------------------------------------------------------- values


def test_the_stepper_mock_is_selected_with_the_only_value_the_stepper_understands(catalogue):
    """The stepper does `os.getenv("MOCK_HARDWARE", "0") == "1"`: "true" selects the REAL motor driver on a Pi."""
    assert catalogue.services["stepper"].env["MOCK_HARDWARE"] == "1"
    stepper_file = (ROOT / "config" / "services" / "stepper.toml").read_text(encoding="utf-8")
    assert "#MOCK_HARDWARE = 1" in stepper_file  # the safe default, listed in the stepper's own settings file
    layout = (ROOT / "config" / "layouts" / "stepper-on-pi.toml").read_text(encoding="utf-8")
    assert "MOCK_HARDWARE = 0 in config/local/stepper.toml" in layout  # how the Pi's owner switches the driver on


def test_variables_every_service_reads_through_shared_logging_are_never_flagged_as_typos(config):
    settings = {name: "x" for name in sorted(SHARED_LOGGING_VARS - {"SERVICE_NAME"})}
    config.layout({"robot": ["tts"]}).env("tts", **settings, TTS_SPEECH_RATTE="1")
    warnings = resolve_env(config.host("robot"), "tts", "SERVICE_PORT=1\n").warnings
    assert len(warnings) == 1 and "TTS_SPEECH_RATTE" in warnings[0]  # a real typo is still caught


def test_credentials_are_masked_including_the_trace_export_headers_but_settings_are_not():
    for key in ("OPENAI_API_KEY", "GITHUB_PAT", "LANGFUSE_SECRET_KEY", "TRACE_EXPORT_HEADERS", "GITHUB_API_KEY"):
        assert is_secret(key), key
    for key in ("MICROPHONE_TARGET_KEYWORDS", "SPEAKER_DEVICE_KEYWORDS", "TRACE_EXPORT_URL", "STEPPER_CONFIGS", "LOG_FORMAT"):
        assert not is_secret(key), key


def test_a_github_key_under_its_alias_counts_as_an_llm_provider(config):
    config.layout({"robot": ["ai-agent"]}).env("ai-agent", GITHUB_API_KEY="not-a-real-key")
    assert resolve_env(config.host("robot"), "ai-agent", None).warnings == []


# --------------------------------------------------------------------------- Brain and the stepper agree


def stepper_service(config: Config, stepper_example: str | None, brain_example: str = "", stepper_env: str = ""):
    """Brain and the stepper on machine ``m``, everything else on ``other``; their ``.env.example`` files as given."""
    config.layout(
        {"m": ["brain", "stepper"], "other": ["microphone", "stt", "tts", "speaker", "ai-agent"]},
        addresses={"m": "10.0.0.1", "other": "10.0.0.2"},
    ).machine("m", workdir=config.base / "work")
    if stepper_env:
        config.local("stepper", f"[env]\n{stepper_env}\n")
    host = config.host("m")
    for name, text in (("stepper", stepper_example), ("brain", brain_example)):
        if text is not None:
            folder = host.service_dir(name)
            folder.mkdir(parents=True)
            (folder / ".env.example").write_text(text)
    return new_deployment_service(host, config.catalogue, shell=Shell(dry_run=True))


TWO = "STEPPER_CONFIGS='{\"stepper_1\": {\"step\": 17, \"dir\": 27, \"en\": 5}, \"stepper_2\": {\"step\": 23, \"dir\": 24, \"en\": 25}}'\n"
ARMS = "STEPPER_LEFT_ARM_STEPPER_ID=stepper_1\nSTEPPER_RIGHT_ARM_STEPPER_ID=stepper_2\n"


def test_arms_that_match_the_steppers_of_this_machine_are_fine(config):
    assert stepper_service(config, TWO, ARMS).validation.stepper_problems() == []


def test_an_arm_pointing_at_a_stepper_that_does_not_exist_is_an_error(config):
    brain = "STEPPER_LEFT_ARM_STEPPER_ID=stepper_1\nSTEPPER_RIGHT_ARM_STEPPER_ID=stepper_3\n"
    (problem,) = stepper_service(config, TWO, brain).validation.stepper_problems()
    assert "STEPPER_RIGHT_ARM_STEPPER_ID=stepper_3" in problem and "stepper_1, stepper_2" in problem


def test_a_settings_file_can_rename_the_steppers_and_the_check_follows(config):
    one = "STEPPER_CONFIGS = '{\"left\": {\"step\": 1, \"dir\": 2, \"en\": 3}}'"
    problems = stepper_service(config, TWO, ARMS, stepper_env=one).validation.stepper_problems()
    assert len(problems) == 2 and all("left" in p for p in problems)


@pytest.mark.parametrize("value", ["not json", "[]", "{}", '{"a": {"step": 1, "dir": 2}}', '{"a": {"step": "17", "dir": 2, "en": 3}}'])
def test_a_stepper_configuration_the_stepper_could_not_start_with_is_an_error(config, value):
    (problem,) = stepper_service(config, f"STEPPER_CONFIGS='{value}'\n").validation.stepper_problems()
    assert "STEPPER_CONFIGS is invalid" in problem


def test_nothing_is_checked_before_the_code_was_fetched_or_when_the_stepper_is_elsewhere(config):
    assert stepper_service(config, None).validation.stepper_problems() == []
    config.layout(
        {"m": ["brain"], "other": ["microphone", "stt", "tts", "speaker", "ai-agent", "stepper"]},
        addresses={"m": "10.0.0.1", "other": "10.0.0.2"},
    )
    remote_only = new_deployment_service(config.host("m"), config.catalogue, shell=Shell(dry_run=True))
    assert remote_only.validation.stepper_problems() == []


def test_validate_reports_the_stepper_wiring(config):
    brain = "STEPPER_LEFT_ARM_STEPPER_ID=nope\n"
    errors, _ = stepper_service(config, TWO, brain).validate(["stepper", "brain"])
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
