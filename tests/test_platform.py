"""What differs per machine: the Python version, Raspberry Pi detection, requirements files, missing LLM keys."""

from __future__ import annotations

import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from oblivion import config, installer
from oblivion.config import DeployError, load_host, load_registry
from oblivion.envfile import resolve_env
from oblivion.manager import Manager
from oblivion.shell import Shell

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def registry():
    return load_registry(ROOT / "services.toml")


def host_for(tmp_path: Path, registry, body: str):
    path = tmp_path / "h.toml"
    path.write_text(textwrap.dedent(body).replace("WORKDIR", (tmp_path / "work").as_posix()))
    return load_host(str(path), registry)


# --------------------------------------------------------------------------- Python version


def test_ai_agent_declares_the_python_its_pinned_dependencies_need(registry):
    assert registry.services["ai-agent"].min_python == (3, 12)  # ai-sdk-python does not install on 3.11
    assert all(spec.min_python is None for name, spec in registry.services.items() if name != "ai-agent")


def test_an_interpreter_too_old_for_a_service_is_reported_before_anything_is_installed(registry, tmp_path):
    host = host_for(tmp_path, registry, """
        [host]
        workdir = "WORKDIR"
        [services.ai-agent]
    """)
    older = replace(host.services["ai-agent"].spec, min_python=(99, 0))
    host = replace(host, services={"ai-agent": replace(host.services["ai-agent"], spec=older)})
    (error,) = installer.check_python(Shell(dry_run=True), host, ["ai-agent"])
    assert "ai-agent needs Python 99.0+" in error and "[remote]" in error and "[host] python" in error
    with pytest.raises(DeployError, match="needs Python 99.0"):
        Manager(Shell(dry_run=True), host, registry).preflight(["ai-agent"])
    assert not (tmp_path / "work").exists()


def test_a_new_enough_interpreter_passes_and_docker_services_are_not_checked(registry, tmp_path):
    host = host_for(tmp_path, registry, f"""
        [host]
        python = "{Path(sys.executable).as_posix()}"
        workdir = "WORKDIR"
        [services.ai-agent]
        [services.tts]
    """)
    errors = installer.check_python(Shell(dry_run=True), host, ["ai-agent", "tts"])
    assert len(errors) == (0 if sys.version_info >= (3, 12) else 1)  # only ai-agent is ever reported
    assert installer.interpreter_version(Shell(dry_run=True), host) == sys.version_info[:2]


def test_an_unusable_host_python_is_a_clear_error(registry, tmp_path):
    host = host_for(tmp_path, registry, """
        [host]
        python = "definitely-not-a-python"
        workdir = "WORKDIR"
        [services.ai-agent]
    """)
    with pytest.raises(DeployError, match="definitely-not-a-python"):
        installer.check_python(Shell(dry_run=True), host, ["ai-agent"])


# --------------------------------------------------------------------------- Raspberry Pi vs other Linux


@pytest.fixture
def fake_proc(monkeypatch):
    """Pretend to be Linux whose /proc files hold the given text; anything else is unreadable."""
    def install(files: dict[str, str], machine: str = "aarch64"):
        monkeypatch.setattr(config.platform, "system", lambda: "Linux")
        monkeypatch.setattr(config.platform, "machine", lambda: machine)
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
    assert config.detect_os() == ("linux", True)
    fake_proc({"/proc/cpuinfo": "processor: 0\nModel : Raspberry Pi 3 Model B Plus Rev 1.3\n"}, machine="armv7l")
    assert config.detect_os() == ("linux", True)


def test_an_arm_server_is_not_mistaken_for_a_pi(fake_proc):
    """The CPU architecture used to decide this; such a machine has no GPIO and needs the ordinary requirements."""
    fake_proc({"/proc/cpuinfo": "processor: 0\nmodel name: Neoverse-N1\n"}, machine="aarch64")
    assert config.detect_os() == ("linux", False)


def test_only_a_pi_gets_the_gpio_requirements_of_the_stepper(registry, tmp_path):
    spec = registry.services["stepper"]
    folder = tmp_path / "stepper_microservice"
    folder.mkdir()
    for name in ("requirements.windows.txt", "requirements.linux.txt"):
        (folder / name).write_text("fastapi\n")
    chosen = {}
    for label, body in {
        "windows": '[host]\nos = "windows"\n',
        "linux": '[host]\nos = "linux"\n',
        "pi": '[host]\nos = "raspberry"\n',
    }.items():
        host = host_for(tmp_path, registry, body + '[services.stepper]\n')
        path, warning = installer.requirements_file(host, spec, folder)
        chosen[label] = (path.name, warning)
    assert chosen == {
        "windows": ("requirements.windows.txt", None),
        "linux": ("requirements.windows.txt", None),  # no RPi.GPIO: it only builds on a Pi
        "pi": ("requirements.linux.txt", None),
    }


# --------------------------------------------------------------------------- ai-agent without an LLM


def _ai_agent_env(registry, tmp_path: Path, host_env: str = "", secrets: str = ""):
    secrets_file = tmp_path / "s.env"
    secrets_file.write_text(secrets)
    host = host_for(tmp_path, registry, f"""
        [host]
        secrets = "{secrets_file.as_posix()}"
        [services.ai-agent]
        {host_env}
    """)
    return resolve_env(host, "ai-agent", None)


def test_ai_agent_without_any_llm_provider_is_a_warning_naming_what_to_add(registry, tmp_path):
    resolved = _ai_agent_env(registry, tmp_path)
    (warning,) = resolved.warnings
    assert "ai-agent" in warning and "GROQ_API_KEY" in warning and "AI_AGENT__" in warning
    assert resolved.errors == []


def test_a_key_or_a_local_model_makes_the_warning_go_away(registry, tmp_path):
    assert _ai_agent_env(registry, tmp_path, secrets="AI_AGENT__GROQ_API_KEY=not-a-real-key\n").warnings == []
    assert _ai_agent_env(registry, tmp_path, host_env='[services.ai-agent.env]\nOLLAMA_URL = "http://gpu-box:11434"').warnings == []


def test_the_default_profile_endpoints_come_from_the_catalogue_for_every_host_file(registry, tmp_path):
    resolved = _ai_agent_env(registry, tmp_path)
    assert resolved.values["GROQ_URL"] == "https://api.groq.com/openai/v1"
    assert resolved.values["GOOGLE_URL"].startswith("https://generativelanguage.googleapis.com/")
    assert resolved.layer_of["GROQ_URL"] == "registry"
