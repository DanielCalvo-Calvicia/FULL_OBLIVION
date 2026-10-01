"""The topology: the layout of the robot written once, with ports, URLs and bind addresses derived from it."""

from __future__ import annotations

import re
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from oblivion import autostart, cli
from oblivion.config import (
    DeployError, load_host, load_registry, load_topology, normalise_remote, validate_host,
)
from oblivion.envfile import resolve_env
from oblivion.manager import Manager
from oblivion.shell import Shell

ROOT = Path(__file__).resolve().parent.parent

THREE = """
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
    """The shipped catalogue, but rooted in a temporary folder so conventional files can be created."""
    return replace(load_registry(ROOT / "services.toml"), base_dir=tmp_path)


def topology_file(tmp_path: Path, text: str = THREE) -> Path:
    path = tmp_path / "robot.toml"
    path.write_text(textwrap.dedent(text))
    return path


def host(tmp_path, registry, machine: str, text: str = THREE):
    topology_file(tmp_path, text)
    return load_host(machine, registry)


# --------------------------------------------------------------------------- one file describes the robot


def test_a_machine_is_derived_from_the_topology_with_no_host_file(tmp_path, registry):
    server = host(tmp_path, registry, "server")
    assert list(server.services) == ["brain", "ai-agent", "stt", "tts"]
    assert (server.name, server.machine, server.ref) == ("server", "server", "server")
    assert {n: i.port for n, i in server.services.items()} == {n: registry.services[n].port for n in server.services}


def test_the_url_of_every_service_on_another_machine_is_its_machines_address_and_the_catalogue_port(tmp_path, registry):
    server = host(tmp_path, registry, "server")
    assert server.remote == {
        "microphone": f"http://192.168.1.20:{registry.services['microphone'].port}",
        "speaker": f"http://192.168.1.20:{registry.services['speaker'].port}",
        "stepper": f"http://192.168.1.30:{registry.services['stepper'].port}",
    }
    assert host(tmp_path, registry, "pc").remote["brain"] == f"http://192.168.1.10:{registry.services['brain'].port}"


def test_an_ipv6_address_is_bracketed_in_the_urls(tmp_path, registry):
    text = THREE.replace("192.168.1.20", "fe80::20")
    assert host(tmp_path, registry, "server", text).remote["microphone"] == "http://[fe80::20]:8000"


def test_a_machine_binds_to_the_network_only_when_another_machine_calls_it(tmp_path, registry):
    assert host(tmp_path, registry, "pc").bind == "0.0.0.0"  # brain, on the server, calls the microphone and the speaker
    assert host(tmp_path, registry, "pi").bind == "0.0.0.0"  # ...and the stepper
    assert host(tmp_path, registry, "server").bind == "127.0.0.1"  # nothing on another machine calls brain, stt, tts or ai-agent


def test_everything_on_one_machine_is_never_exposed(tmp_path, registry):
    alone = host(tmp_path, registry, "robot", """
        [machines.robot]
        address = "192.168.1.5"
        services = ["brain", "microphone", "stt", "tts", "speaker", "ai-agent", "stepper"]
    """)
    assert alone.bind == "127.0.0.1" and alone.remote == {}


def test_a_port_that_deviates_from_the_catalogue_is_written_once_and_reaches_the_service_and_its_callers(tmp_path, registry):
    text = THREE.replace('services = ["stepper"]', 'services = ["stepper"]\n    ports = { stepper = 18005 }')
    assert host(tmp_path, registry, "pi", text).services["stepper"].port == 18005
    assert host(tmp_path, registry, "server", text).remote["stepper"] == "http://192.168.1.30:18005"
    server_env = resolve_env(host(tmp_path, registry, "server", text), "brain", None).values
    assert server_env["STEPPER_BASE_URL"] == "http://192.168.1.30:18005"
    assert resolve_env(host(tmp_path, registry, "pi", text), "stepper", None).values["SERVICE_PORT"] == "18005"


def test_each_machine_gets_the_addresses_ports_and_bind_it_needs_in_its_services_environment(tmp_path, registry):
    pc, server = host(tmp_path, registry, "pc"), host(tmp_path, registry, "server")
    mic = resolve_env(pc, "microphone", None).values
    assert (mic["SERVICE_HOST"], mic["SERVICE_PORT"]) == ("0.0.0.0", str(registry.services["microphone"].port))
    brain = resolve_env(server, "brain", None).values
    assert brain["SERVICE_HOST"] == "127.0.0.1"
    assert brain["MICROPHONE_BASE_URL"] == "http://192.168.1.20:8000" and brain["STT_BASE_URL"] == "http://127.0.0.1:8001"
    assert brain["STEPPER_BASE_URL"] == "http://192.168.1.30:8005" and brain["AI_AGENT_BASE_URL"] == "http://127.0.0.1:7998"


def test_the_layout_is_valid_for_every_machine_and_a_missing_service_names_the_topology(tmp_path, registry):
    for machine in ("pc", "server", "pi"):
        errors, _ = validate_host(host(tmp_path, registry, machine))
        assert errors == [], f"{machine}: {errors}"
    without_speaker = THREE.replace('["microphone", "speaker"]', '["microphone"]')
    errors, _ = validate_host(host(tmp_path, registry, "server", without_speaker))
    assert any("brain needs 'speaker': add it to a machine of the topology" in e for e in errors)


# --------------------------------------------------------------------------- mistakes in the topology


@pytest.mark.parametrize("text,message", [
    ("", "no [machines"),
    ('[machines.a]\nservices = ["brain"]\n', "needs address"),
    ('[machines.a]\naddress = "http://192.168.1.2:8000"\nservices = ["brain"]\n', "no http://, no port"),
    ('[machines.a]\naddress = "192.168.1.2:8000"\nservices = ["brain"]\n', "ports come from services.toml"),
    ('[machines.a]\naddress = "192 168"\nservices = ["brain"]\n', "needs address"),
    ('[machines.a]\naddress = "10.0.0.1"\nservices = ["braim"]\n', "unknown service 'braim'"),
    ('[machines.a]\naddress = "10.0.0.1"\nservices = ["stt"]\n[machines.b]\naddress = "10.0.0.2"\nservices = ["stt"]\n', "placed on both 'a' and 'b'"),
    ('[machines.a]\naddress = "10.0.0.1"\nservices = ["stt"]\nports = { tts = 1 }\n', "sets a port for 'tts'"),
])
def test_a_wrong_topology_says_what_is_wrong(tmp_path, registry, text, message):
    path = topology_file(tmp_path, text)
    with pytest.raises(DeployError, match=re.escape(message)):
        load_topology(path, registry)


def test_no_topology_file_is_not_an_error_until_a_machine_needs_it(tmp_path, registry):
    assert load_topology(tmp_path / "robot.toml", registry) is None
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hosts" / "x.toml").write_text('[host]\nmachine = "server"\n')
    with pytest.raises(DeployError, match="there is no robot.toml"):
        load_host("x", registry)


# --------------------------------------------------------------------------- a host file only overrides


def host_file(tmp_path: Path, name: str, text: str) -> None:
    (tmp_path / "hosts").mkdir(exist_ok=True)
    (tmp_path / "hosts" / f"{name}.toml").write_text(textwrap.dedent(text))


def test_a_host_file_names_its_machine_and_adds_only_overrides(tmp_path, registry):
    topology_file(tmp_path)
    host_file(tmp_path, "server", """
        [host]
        machine = "server"
        python = "python3.12"
        [defaults]
        branch = "v1"
        [services.stt]
        runtime = "docker"
        [services.tts]
        branch = "v2"
        [services.tts.env]
        TTS_SPEECH_RATE = "120"
    """)
    server = load_host("server", registry)
    assert list(server.services) == ["brain", "ai-agent", "stt", "tts"]  # still the topology's
    assert server.python == "python3.12" and server.services["stt"].runtime == "docker"
    assert [server.services[n].branch for n in ("brain", "stt", "tts")] == ["v1", "v1", "v2"]
    assert server.services["tts"].env == {"TTS_SPEECH_RATE": "120"}
    assert server.remote["speaker"] == "http://192.168.1.20:8003" and server.bind == "127.0.0.1"
    assert server.ref.endswith("server.toml")  # named by its file for the boot start


def test_a_host_file_cannot_add_a_service_the_topology_places_elsewhere(tmp_path, registry):
    topology_file(tmp_path)
    host_file(tmp_path, "server", '[host]\nmachine = "server"\n[services.speaker]\n')
    with pytest.raises(DeployError, match=r"\[services.speaker\] is not one of the services of machine 'server'.*runs on 'pc'"):
        load_host("server", registry)


def test_an_unknown_machine_lists_the_known_ones(tmp_path, registry):
    topology_file(tmp_path)
    host_file(tmp_path, "x", '[host]\nmachine = "laptop"\n')
    with pytest.raises(DeployError, match="machine 'laptop' is not in robot.toml \\(has: pc, server, pi\\)"):
        load_host("x", registry)


def test_bind_and_remote_written_by_hand_win_over_the_derived_ones(tmp_path, registry):
    topology_file(tmp_path)
    host_file(tmp_path, "server", """
        [host]
        machine = "server"
        bind = "10.9.9.9"
        [remote]
        stepper = "192.168.7.7"
        speaker = "192.168.7.8:9999"
        microphone = "https://mic.example"
    """)
    server = load_host("server", registry)
    assert server.bind == "10.9.9.9"
    assert server.remote["stepper"] == "http://192.168.7.7:8005"  # a bare address gets the catalogue's port
    assert server.remote["speaker"] == "http://192.168.7.8:9999"
    assert server.remote["microphone"] == "https://mic.example"  # a full URL is left alone


@pytest.mark.parametrize("value,expected", [
    ("192.168.1.20", "http://192.168.1.20:8000"), ("192.168.1.20:9", "http://192.168.1.20:9"),
    ("robot.lan", "http://robot.lan:8000"), ("http://a:1/", "http://a:1"), ("https://a", "https://a"),
    ("[fe80::1]", "http://[fe80::1]:8000"), ("[fe80::1]:9", "http://[fe80::1]:9"),
])
def test_a_remote_entry_may_be_a_bare_address_an_address_with_a_port_or_a_url(registry, value, expected):
    assert normalise_remote("microphone", value, registry) == expected


def test_the_env_file_of_a_machine_is_secrets_slash_machine_env_when_it_exists(tmp_path, registry):
    assert host(tmp_path, registry, "server").env_file is None  # nothing to read: no warning either
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "server.env").write_text("STT__OPENAI_API_KEY=key-not-real\n")
    server = load_host("server", registry)
    assert server.env_file == (tmp_path / "secrets" / "server.env").resolve()
    assert resolve_env(server, "stt", None).values["OPENAI_API_KEY"] == "key-not-real"


def test_a_plan_of_a_machine_needs_nothing_but_the_topology(tmp_path, registry):
    lines = Manager(Shell(dry_run=True), host(tmp_path, registry, "server"), registry).plan_lines(None)
    text = "\n".join(lines)
    assert "host server: " in text and "bind 127.0.0.1" in text
    assert "MICROPHONE_BASE_URL=http://192.168.1.20:8000" in text and "remote stepper" in text


# --------------------------------------------------------------------------- the commands


def test_the_topology_command_shows_every_machine_and_what_it_exposes(tmp_path, registry, capsys):
    path = topology_file(tmp_path)
    assert cli.main(["topology", "--robot", str(path)]) == 0
    out = capsys.readouterr().out
    assert "3 machines" in out and "pc  192.168.1.20   bind 0.0.0.0" in out
    assert "runs   microphone port 8000  <- called from other machines" in out
    assert "calls  speaker    http://192.168.1.20:8003" in out and out.rstrip().endswith("OK")


def test_the_topology_command_fails_when_a_machine_cannot_find_what_it_needs(tmp_path, capsys):
    path = topology_file(tmp_path, THREE.replace('["stepper"]', '["stepper"]').replace('["microphone", "speaker"]', '["microphone"]'))
    assert cli.main(["topology", "--robot", str(path)]) == 1
    out = capsys.readouterr().out
    assert "ERROR  brain needs 'speaker'" in out and "1 error(s)" in out
    assert "not placed on any machine: speaker" in out  # ...and it says which one is missing


def test_the_topology_command_without_a_file_says_how_to_make_one(tmp_path, capsys):
    assert cli.main(["topology", "--robot", str(tmp_path / "nope.toml")]) == 2
    assert "robot.example.toml" in capsys.readouterr().err


def test_the_ordinary_commands_take_a_machine_name_and_a_topology_file(tmp_path, capsys):
    path = topology_file(tmp_path)
    assert cli.main(["validate", "--host", "pc", "--robot", str(path)]) == 0
    assert cli.main(["plan", "--host", "pi", "--robot", str(path), "--service", "stepper"]) == 0
    assert "SERVICE_HOST=0.0.0.0" in capsys.readouterr().out


def test_the_boot_start_of_a_machine_names_the_machine_and_the_topology_file(tmp_path, registry):
    implicit = host(tmp_path, registry, "pc")
    command = autostart._cli_command(implicit, "start")
    assert command[-4:] == ["--host", "pc", "--robot", str((tmp_path / "robot.toml").resolve())]
    assert "pc" in autostart.systemd_unit(implicit)
    plain = load_host(str(ROOT / "hosts" / "all-in-one.example.toml"), load_registry(ROOT / "services.toml"))
    assert autostart._cli_command(plain, "start")[-2:] == ["--host", str(plain.source)] and "--robot" not in autostart._cli_command(plain, "start")


# --------------------------------------------------------------------------- what ships


def test_the_shipped_example_places_every_service_exactly_once_and_every_machine_is_valid():
    registry = load_registry(ROOT / "services.toml")
    topology = load_topology(ROOT / "robot.example.toml", registry)
    placed = [service for machine in topology.machines.values() for service in machine.services]
    assert sorted(placed) == sorted(registry.services)
    for machine in topology.machines:
        errors, _ = validate_host(load_host(machine, registry, ROOT / "robot.example.toml", from_topology=True))
        assert errors == [], f"{machine}: {errors}"


def test_a_real_topology_is_never_committed_but_the_example_is():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    patterns = [line.strip() for line in ignored.splitlines() if line.strip() and not line.startswith("#")]
    assert "/robot.toml" in patterns and "robot.example.toml" not in patterns


@pytest.mark.parametrize("doc", ["docs/DEPLOYMENT.md", "docs/USER_GUIDE.md"])
def test_the_ports_the_docs_print_are_the_ones_of_the_catalogue(doc):
    """A port is defined once, in services.toml. Wherever the docs repeat it in a service table, it must agree."""
    registry = load_registry(ROOT / "services.toml")
    text = (ROOT / doc).read_text(encoding="utf-8")
    for name, spec in registry.services.items():
        rows = [line for line in text.splitlines() if re.match(rf"^\| `?{re.escape(name)}`? \|", line) and re.search(r"\b\d{4}\b", line)]
        assert rows, f"{doc} has no table row with a port for {name}"
        assert all(re.search(rf"\b{spec.port}\b", row) for row in rows), f"{doc}: {name} is not on port {spec.port} in: {rows}"
