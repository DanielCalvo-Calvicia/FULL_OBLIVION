"""The committed settings files list every setting of every service, and satisfy all seven services when switched on."""

from __future__ import annotations

import re
import shutil
import sys
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
from conftest import Config, shipped_layout_hosts

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import env_inventory  # noqa: E402

from composition_root.container import new_deployment_service  # noqa: E402
from domain.rules.env_names import SHARED_LOGGING_VARS, TUNING_VARS, computed_variables, is_secret, known_variables, mask  # noqa: E402
from domain.rules.env_resolution import resolve_env  # noqa: E402
from infrastructure.config.host_loader import load_host  # noqa: E402
from infrastructure.config.paths import ConfigPaths  # noqa: E402
from infrastructure.config.settings_loader import load_settings  # noqa: E402
from infrastructure.inbound.cli import cli  # noqa: E402
from infrastructure.outbound.shell.shell import Shell  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent
SERVICES_DIR = ROOT / "config" / "services"
needs_workspace = pytest.mark.skipif(
    not all((WORKSPACE / name).exists() for name in ("brain_microservice", "ai-agent", "stepper_microservice")),
    reason="no workspace next to this repository",
)


def activate(text: str) -> str:
    """A settings file with every commented-out variable switched on and every secret given a (dummy) value."""
    lines = [(m.group(1) if (m := re.match(r"^#([A-Z][A-Z0-9_]* = .*)$", line)) else line) for line in text.splitlines()]

    def fill(match: re.Match[str]) -> str:
        return f'{match.group(1)} = "dummy-not-a-real-secret"' if is_secret(match.group(1)) else match.group(0)

    return re.sub(r'^([A-Z][A-Z0-9_]*) = ""$', fill, "\n".join(lines), flags=re.M) + "\n"


def listed_variables(path: Path) -> set[str]:
    """The variable names a settings file lists, commented-out ones included."""
    return {m.group(1) for line in path.read_text(encoding="utf-8").splitlines() if (m := re.match(r"^#?([A-Z][A-Z0-9_]*) = ", line))}


# --------------------------------------------------------------------------- the files list everything


@needs_workspace
def test_every_variable_a_service_reads_or_documents_is_in_its_file_or_in_all(catalogue):
    shared = listed_variables(SERVICES_DIR / "all.toml")
    missing = []
    for name, spec in catalogue.services.items():
        folder = WORKSPACE / spec.repo_dir
        wanted = env_inventory.code_variables(folder) | set(env_inventory.parse_example((folder / ".env.example").read_text(encoding="utf-8")))
        wanted -= SHARED_LOGGING_VARS | computed_variables(spec)
        wanted = {v for v in wanted if not any(fnmatchcase(v, pattern) for pattern in spec.internal)}  # never advertised
        own = listed_variables(SERVICES_DIR / f"{name}.toml")
        missing += [f"{name}: {v}" for v in sorted(wanted) if v not in own and v not in shared]
    assert missing == [], "add to scripts/env_inventory.py (EXTRA) or fix the source, then --write"
    assert SHARED_LOGGING_VARS - TUNING_VARS <= shared


def test_no_variable_is_listed_twice_across_the_settings_files():
    """A variable several services use is listed once, in all.toml; a service's own file lists only its own."""
    names = [v for path in SERVICES_DIR.glob("*.toml") for v in listed_variables(path)]
    assert sorted({n for n in names if names.count(n) > 1}) == []


def test_nothing_real_is_in_the_committed_files():
    for path in [*SERVICES_DIR.glob("*.toml"), *(ROOT / "config" / "local").glob("*.example.toml")]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b(sk-[A-Za-z0-9]{10,}|AIza[0-9A-Za-z_-]{20,}|gsk_[A-Za-z0-9]{10,})", text), path.name
        for line in text.splitlines():
            if (m := re.match(r"^([A-Z][A-Z0-9_]*) = (.*)$", line)) and is_secret(m.group(1)):
                assert m.group(2) == '""', f"{path.name}: an active secret must be empty: {line}"


def test_only_real_secrets_get_a_dummy_value_when_a_file_is_activated():
    activated = activate((SERVICES_DIR / "ai-agent.toml").read_text(encoding="utf-8") + (SERVICES_DIR / "all.toml").read_text(encoding="utf-8"))
    assert re.search(r'^GROQ_API_KEY = "dummy-not-a-real-secret"$', activated, re.M)
    assert re.search(r'^OPENAI_API_KEY = "dummy-not-a-real-secret"$', activated, re.M)
    assert not re.search(r'^[A-Z_]*KEYWORDS = "dummy', activated, re.M)  # KEYWORDS is a setting, not a key


# --------------------------------------------------------------------------- ...and they satisfy every service


@needs_workspace
def test_every_setting_switched_on_satisfies_all_seven_services_on_every_shipped_layout(tmp_path, catalogue):
    """Every line on: no service may reject, not know, or fail to receive any of its variables."""
    problems, seen = [], set()
    for layout, machine, host in shipped_layout_hosts(tmp_path, catalogue):
        config_dir = host.config_dir
        for source in SERVICES_DIR.glob("*.toml"):
            target = config_dir / "services" / source.name
            target.parent.mkdir(exist_ok=True)
            target.write_text(activate(source.read_text(encoding="utf-8")), encoding="utf-8")
        paths = ConfigPaths(config_dir)
        host = load_host(machine, catalogue, paths)
        shared_values = load_settings(paths.services, paths, catalogue)["all"].env  # what all.toml sets, now that it is switched on
        assert shared_values, "the shared file sets nothing when switched on"
        for name, instance in host.services.items():
            seen.add(name)
            example = (WORKSPACE / instance.spec.repo_dir / ".env.example").read_text(encoding="utf-8")
            resolved = resolve_env(host, name, example)
            problems += [f"{layout}/{name}: {m}" for m in [*resolved.errors, *resolved.warnings]]
            uses, _ = known_variables(instance.spec, example)
            own_layer = f"config/services/{name}.toml"
            for variable in listed_variables(SERVICES_DIR / f"{name}.toml"):
                if resolved.layer_of.get(variable) != own_layer:
                    problems.append(f"{layout}/{name}: {variable} did not arrive from {own_layer}")
            for variable, value in shared_values.items():
                reached = resolved.layer_of.get(variable) == "config/services/all.toml" and resolved.values.get(variable) == value
                if uses(variable) and variable != "SERVICE_NAME" and variable not in listed_variables(SERVICES_DIR / f"{name}.toml") and not reached:
                    problems.append(f"{layout}/{name}: shared {variable} did not reach a service that uses it")
                if not uses(variable) and variable in resolved.values and resolved.layer_of[variable] == "config/services/all.toml":
                    problems.append(f"{layout}/{name}: shared {variable} reached a service that does not use it")
    assert seen == set(catalogue.services) and problems == []


# --------------------------------------------------------------------------- values and output


def test_a_value_may_be_a_string_a_number_or_a_boolean(config):
    config.layout({"robot": ["brain"]}).local(
        "brain", "[env]\nSTARTUP_PREFLIGHT_TIMEOUT_SECONDS = 90\nSTARTUP_PREFLIGHT_ENABLED = false\nSTEPPER_DEFAULT_RPM = 12.5\nPROVIDER_NAME = 'local'\n"
    )
    (layer,) = config.host("robot").services["brain"].layers
    assert layer.values == {
        "STARTUP_PREFLIGHT_TIMEOUT_SECONDS": "90", "STARTUP_PREFLIGHT_ENABLED": "false",
        "STEPPER_DEFAULT_RPM": "12.5", "PROVIDER_NAME": "local",
    }


def test_a_missing_key_says_which_file_to_put_it_in_and_validate_reports_it(config):
    config.layout({"robot": ["stt"]})
    service = new_deployment_service(config.host("robot"), config.catalogue, shell=Shell(dry_run=True))
    (error,) = resolve_env(config.host("robot"), "stt", None).errors
    assert 'OPENAI_API_KEY is required when STT_ENGINE=openai; set OPENAI_API_KEY = "..." in config/local/stt.toml' in error
    errors, _ = service.validate(["stt"])
    assert any("config/local/stt.toml" in e for e in errors)
    config.env("stt", OPENAI_API_KEY="key-not-real")
    assert resolve_env(config.host("robot"), "stt", None).errors == []


def test_a_key_is_masked_in_the_env_command_output(config, capsys):
    shutil.copy(ROOT / "config" / "catalogue.toml", config.paths.catalogue)
    shutil.copytree(ROOT / "wheels", config.base / "wheels")
    config.layout({"robot": ["stt"]}).env("stt", OPENAI_API_KEY="sk-not-a-real-key")
    assert cli.main(["env", "stt", "--host", "robot", "--config", str(config.paths.root)]) == 0
    out = capsys.readouterr().out
    assert "OPENAI_API_KEY=********    # config/local/stt.toml" in out and "sk-not-a-real-key" not in out
    assert mask("OPENAI_API_KEY", "sk-not-a-real-key") == "********"


def test_the_generated_env_of_a_service_carries_the_settings_values(config, tmp_path):
    config.layout({"robot": ["stt"]}).machine("robot", workdir=tmp_path / "work")
    config.local("all", "[env]\nLOG_LEVEL = 'DEBUG'\n")
    config.env("stt", STT_LANGUAGE="es", OPENAI_API_KEY="key-not-real")
    new_deployment_service(config.host("robot"), config.catalogue, shell=Shell(echo=False)).write_env("stt")
    env = (tmp_path / "work" / "services" / "stt_microservice" / ".env").read_text()
    assert "LOG_LEVEL=DEBUG\n" in env and "STT_LANGUAGE=es\n" in env and "OPENAI_API_KEY=key-not-real\n" in env
    assert "SERVICE_PORT=8001\n" in env  # ...next to the port derived from the catalogue
    assert env.startswith("# Generated by oblivion for machine robot.")
