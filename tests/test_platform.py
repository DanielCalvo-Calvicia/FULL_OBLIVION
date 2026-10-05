"""What differs per machine: the Python version, Raspberry Pi detection, requirements files, missing LLM keys."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from composition_root.container import new_deployment_service
from domain.errors import DeployError
from domain.rules.env_resolution import resolve_env
from infrastructure.config import machine_loader
from infrastructure.outbound.installer import native_installer as installer
from infrastructure.outbound.installer.native_installer import NativeInstaller
from infrastructure.outbound.shell.shell import Shell

# --------------------------------------------------------------------------- Python version


def test_ai_agent_declares_the_python_its_pinned_dependencies_need(catalogue):
    assert catalogue.services["ai-agent"].min_python == (3, 12)  # ai-sdk-python does not install on 3.11
    assert all(spec.min_python is None for name, spec in catalogue.services.items() if name != "ai-agent")


def test_an_interpreter_too_old_for_a_service_is_reported_before_anything_is_installed(config, tmp_path):
    config.layout({"robot": ["ai-agent"]}).machine("robot", workdir=tmp_path / "work")
    host = config.host("robot")
    older = replace(host.services["ai-agent"].spec, min_python=(99, 0))
    host = replace(host, services={"ai-agent": replace(host.services["ai-agent"], spec=older)})
    (error,) = NativeInstaller(Shell(dry_run=True)).check_python(host, ["ai-agent"])
    assert "ai-agent needs Python 99.0+" in error and "config/layouts/" in error and "config/machines/robot.toml" in error
    with pytest.raises(DeployError, match="needs Python 99.0"):
        new_deployment_service(host, config.catalogue, shell=Shell(dry_run=True)).preflight(["ai-agent"])
    assert not (tmp_path / "work").exists()


def test_a_new_enough_interpreter_passes_and_docker_services_are_not_checked(config, tmp_path):
    config.layout({"robot": ["ai-agent", "tts"]}).machine("robot", python=Path(sys.executable), workdir=tmp_path / "work")
    host = config.host("robot")
    errors = NativeInstaller(Shell(dry_run=True)).check_python(host, ["ai-agent", "tts"])
    assert len(errors) == (0 if sys.version_info >= (3, 12) else 1)  # only ai-agent is ever reported
    assert NativeInstaller(Shell(dry_run=True)).interpreter_version(host) == sys.version_info[:2]


def test_an_unusable_machine_python_is_a_clear_error(config, tmp_path):
    config.layout({"robot": ["ai-agent"]}).machine("robot", python="definitely-not-a-python", workdir=tmp_path / "work")
    with pytest.raises(DeployError, match="definitely-not-a-python"):
        NativeInstaller(Shell(dry_run=True)).check_python(config.host("robot"), ["ai-agent"])


# --------------------------------------------------------------------------- Raspberry Pi vs other Linux


@pytest.fixture
def fake_proc(monkeypatch):
    """Pretend to be Linux whose /proc files hold the given text; anything else is unreadable."""
    def install(files: dict[str, str], machine: str = "aarch64"):
        monkeypatch.setattr(machine_loader.platform, "system", lambda: "Linux")
        monkeypatch.setattr(machine_loader.platform, "machine", lambda: machine)
        original = Path.read_text

        def read_text(self, *args, **kwargs):
            key = self.as_posix()
            if key in files:
                return files[key]
            if key.startswith("/proc/"):
                raise OSError(key)
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", read_text)
    return install


def test_a_pi_is_recognised_by_what_the_board_says(fake_proc):
    fake_proc({"/proc/device-tree/model": "Raspberry Pi 4 Model B Rev 1.4"})
    assert machine_loader.detect_os() == ("linux", True)
    fake_proc({"/proc/cpuinfo": "processor: 0\nModel : Raspberry Pi 3 Model B Plus Rev 1.3\n"}, machine="armv7l")
    assert machine_loader.detect_os() == ("linux", True)


def test_an_arm_server_is_not_mistaken_for_a_pi(fake_proc):
    """The CPU architecture used to decide this; such a machine has no GPIO and needs the ordinary requirements."""
    fake_proc({"/proc/cpuinfo": "processor: 0\nmodel name: Neoverse-N1\n"}, machine="aarch64")
    assert machine_loader.detect_os() == ("linux", False)


def test_only_a_pi_gets_the_gpio_requirements_of_the_stepper(config, tmp_path):
    spec = config.catalogue.services["stepper"]
    folder = tmp_path / "stepper_microservice"
    folder.mkdir()
    for name in ("requirements.windows.txt", "requirements.linux.txt"):
        (folder / name).write_text("fastapi\n")
    config.layout({"robot": ["stepper"]})
    chosen = {}
    for label, os_name in {"windows": "windows", "linux": "linux", "pi": "raspberry"}.items():
        config.machine("robot", os=os_name)
        path, warning = installer.requirements_file(config.host("robot"), spec, folder)
        chosen[label] = (path.name, warning)
    assert chosen == {
        "windows": ("requirements.windows.txt", None),
        "linux": ("requirements.windows.txt", None),  # no RPi.GPIO: it only builds on a Pi
        "pi": ("requirements.linux.txt", None),
    }


# --------------------------------------------------------------------------- ai-agent without an LLM


def _ai_agent_env(config, **env):
    config.layout({"robot": ["ai-agent"]})
    if env:
        config.env("ai-agent", **env)
    return resolve_env(config.host("robot"), "ai-agent", None)


def test_ai_agent_without_any_llm_provider_is_a_warning_naming_what_to_add(config):
    resolved = _ai_agent_env(config)
    (warning,) = resolved.warnings
    assert "ai-agent" in warning and "GROQ_API_KEY" in warning and "config/local/ai-agent.toml" in warning
    assert resolved.errors == []


def test_a_key_or_a_local_model_makes_the_warning_go_away(config):
    assert _ai_agent_env(config, GROQ_API_KEY="not-a-real-key").warnings == []
    assert _ai_agent_env(config, OLLAMA_URL="http://gpu-box:11434").warnings == []


def test_the_default_profile_endpoints_come_from_the_catalogue(config):
    resolved = _ai_agent_env(config)
    assert resolved.values["GROQ_URL"] == "https://api.groq.com/openai/v1"
    assert resolved.values["GOOGLE_URL"].startswith("https://generativelanguage.googleapis.com/")
    assert resolved.layer_of["GROQ_URL"] == "catalogue"
