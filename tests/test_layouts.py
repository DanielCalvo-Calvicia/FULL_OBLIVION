"""Layouts: where each service runs, written once, with ports, URLs and bind addresses derived from it."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from conftest import ALL_SERVICES, Config

from application.dtos.options import Options
from composition_root.container import new_deployment_service
from domain.errors import DeployError
from domain.rules.env_resolution import resolve_env
from domain.rules.host_validation import validate_host
from infrastructure.config.layout_loader import load_layout
from infrastructure.inbound.cli import cli
from infrastructure.outbound.autostart import autostart
from infrastructure.outbound.shell.shell import Shell

ROOT = Path(__file__).resolve().parent.parent

THREE = {"pc": ["microphone", "speaker"], "server": ["brain", "ai-agent", "stt", "tts"], "pi": ["stepper"]}
THREE_ADDRESSES = {"pc": "192.168.1.20", "server": "192.168.1.10", "pi": "192.168.1.30"}


def three(config: Config, machines=None, addresses=None, **kwargs) -> Config:
    return config.layout(machines or THREE, addresses or THREE_ADDRESSES, **kwargs)


def with_catalogue(config: Config) -> Config:
    """The shipped catalogue and wheels inside the temporary folder, so the command line can run against it."""
    shutil.copy(ROOT / "config" / "catalogue.toml", config.paths.catalogue)
    shutil.copytree(ROOT / "wheels", config.base / "wheels", dirs_exist_ok=True)
    return config


# --------------------------------------------------------------------------- one layout describes the robot


def test_a_machine_is_derived_from_the_layout(config, catalogue):
    server = three(config).host("server")
    assert list(server.services) == ["brain", "ai-agent", "stt", "tts"]
    assert server.name == "server"
    assert {n: i.port for n, i in server.services.items()} == {n: catalogue.services[n].port for n in server.services}


def test_the_url_of_every_service_on_another_machine_is_its_machines_address_and_the_catalogue_port(config, catalogue):
    three(config)
    assert config.host("server").remote == {
        "microphone": f"http://192.168.1.20:{catalogue.services['microphone'].port}",
        "speaker": f"http://192.168.1.20:{catalogue.services['speaker'].port}",
        "stepper": f"http://192.168.1.30:{catalogue.services['stepper'].port}",
    }
    assert config.host("pc").remote["brain"] == f"http://192.168.1.10:{catalogue.services['brain'].port}"


def test_an_ipv6_address_is_bracketed_in_the_urls(config):
    three(config, addresses={**THREE_ADDRESSES, "pc": "fe80::20"})
    assert config.host("server").remote["microphone"] == "http://[fe80::20]:8000"


def test_a_machine_binds_to_the_network_only_when_another_machine_calls_it(config):
    three(config)
    assert config.host("pc").bind == "0.0.0.0"  # brain, on the server, calls the microphone and the speaker
    assert config.host("pi").bind == "0.0.0.0"  # ...and the stepper
    assert config.host("server").bind == "127.0.0.1"  # nothing on another machine calls brain, stt, tts or ai-agent


def test_everything_on_one_machine_is_never_exposed(config):
    alone = config.layout({"robot": ALL_SERVICES}, {"robot": "192.168.1.5"}).host("robot")
    assert alone.bind == "127.0.0.1" and alone.remote == {}


def test_a_port_that_deviates_from_the_catalogue_is_written_once_and_reaches_the_service_and_its_callers(config):
    three(config, ports={"pi": {"stepper": 18005}})
    assert config.host("pi").services["stepper"].port == 18005
    assert config.host("server").remote["stepper"] == "http://192.168.1.30:18005"
    assert resolve_env(config.host("server"), "brain", None).values["STEPPER_BASE_URL"] == "http://192.168.1.30:18005"
    assert resolve_env(config.host("pi"), "stepper", None).values["SERVICE_PORT"] == "18005"


def test_each_machine_gets_the_addresses_ports_and_bind_it_needs_in_its_services_environment(config, catalogue):
    three(config)
    mic = resolve_env(config.host("pc"), "microphone", None).values
    assert (mic["SERVICE_HOST"], mic["SERVICE_PORT"]) == ("0.0.0.0", str(catalogue.services["microphone"].port))
    brain = resolve_env(config.host("server"), "brain", None).values
    assert brain["SERVICE_HOST"] == "127.0.0.1"
    assert brain["MICROPHONE_BASE_URL"] == "http://192.168.1.20:8000" and brain["STT_BASE_URL"] == "http://127.0.0.1:8001"
    assert brain["STEPPER_BASE_URL"] == "http://192.168.1.30:8005" and brain["AI_AGENT_BASE_URL"] == "http://127.0.0.1:7998"


def test_the_layout_is_valid_for_every_machine_and_a_missing_service_says_where_to_add_it(config):
    three(config)
    for machine in ("pc", "server", "pi"):
        errors, _ = validate_host(config.host(machine))
        assert errors == [], f"{machine}: {errors}"
    three(config, machines={**THREE, "pc": ["microphone"]})
    errors, _ = validate_host(config.host("server"))
    assert any("brain needs 'speaker': put it on a machine of the layout (config/layouts/)" in e for e in errors)


# --------------------------------------------------------------------------- mistakes in a layout


@pytest.mark.parametrize("text,message", [
    ("description = 'nothing'\n", "no [machines.<name>] tables"),
    ('[machines.a]\nservices = ["brain"]\n', "has no address"),
    ('[machines.a]\naddress = "http://192.168.1.2:8000"\nservices = ["brain"]\n', "no http://, no port"),
    ('[machines.a]\naddress = "192.168.1.2:8000"\nservices = ["brain"]\n', "ports come from config/catalogue.toml"),
    ('[machines.a]\naddress = "192 168"\nservices = ["brain"]\n', "must be an IP or a host name"),
    ('[machines.a]\naddress = "10.0.0.1"\nservices = ["braim"]\n', "unknown service 'braim'"),
    ('[machines.a]\naddress = "10.0.0.1"\nservices = ["stt"]\n[machines.b]\naddress = "10.0.0.2"\nservices = ["stt"]\n', "placed on both 'a' and 'b'"),
    ('[machines.a]\naddress = "10.0.0.1"\nservices = ["stt"]\nports = { tts = 1 }\n', "sets a port for 'tts'"),
    ('[machines.a]\naddress = "10.0.0.1"\nservices = ["stt"]\ncolour = "red"\n', "unknown key(s) colour"),
    ('colour = "red"\n[machines.a]\naddress = "10.0.0.1"\nservices = ["stt"]\n', "unknown key(s) colour"),
])
def test_a_wrong_layout_says_what_is_wrong(config, text, message):
    config.raw_layout(text)
    with pytest.raises(DeployError, match=re.escape(message)):
        config.host("a")


def test_robot_toml_must_exist_and_name_a_layout_that_exists(config):
    with pytest.raises(DeployError, match="copy config/robot.example.toml to config/robot.toml"):
        config.host("pc")
    three(config)
    config.paths.robot.write_text('layout = "nope"\n')
    with pytest.raises(DeployError, match=r"layout 'nope' not found.*available: test"):
        config.host("pc")
    config.paths.robot.write_text("[addresses]\n")
    with pytest.raises(DeployError, match="layout = \"<name>\" is missing"):
        config.host("pc")
    config.paths.robot.write_text('layout = "../escape"\n')
    with pytest.raises(DeployError, match="not a valid name"):
        config.host("pc")


def test_an_address_in_robot_toml_for_a_machine_the_layout_does_not_have_is_an_error(config):
    three(config, addresses={**THREE_ADDRESSES, "laptop": "192.168.1.99"})
    with pytest.raises(DeployError, match=r"names laptop, which layout 'test' does not have \(machines: pc, server, pi\)"):
        config.host("pc")


def test_a_machine_that_is_not_in_the_layout_lists_the_ones_that_are(config):
    three(config)
    with pytest.raises(DeployError, match=r"machine 'laptop' is not in layout 'test' \(machines: pc, server, pi\)"):
        config.host("laptop")


def test_a_missing_address_names_the_machine_and_the_line_to_add(config):
    three(config, addresses={"pc": "192.168.1.20", "server": "192.168.1.10"})
    with pytest.raises(DeployError, match=r"machine 'pi' of layout 'test' has no address: add  pi = \"<ip or host name>\"  under \[addresses\] in config/robot.toml"):
        config.host("pc")


def test_an_address_in_robot_toml_wins_over_the_default_in_the_layout(config):
    config.raw_layout('[machines.robot]\naddress = "127.0.0.1"\nservices = ["stt"]\n', addresses={"robot": "192.168.1.77"})
    assert load_layout(config.paths, config.catalogue).machines["robot"].address == "192.168.1.77"


# --------------------------------------------------------------------------- machine settings


def test_a_machine_file_adds_only_what_is_particular_to_that_machine(config, tmp_path):
    three(config)
    config.machine("server", python="python3.12", os="linux", workdir=tmp_path / "srv", bind="10.9.9.9")
    server = config.host("server")
    assert list(server.services) == ["brain", "ai-agent", "stt", "tts"]  # still the layout's
    assert server.python == "python3.12" and server.os_family == "linux" and not server.is_raspberry
    assert server.workdir == (tmp_path / "srv")
    assert server.bind == "10.9.9.9"  # written by hand: wins over the derived one
    assert server.remote["speaker"] == "http://192.168.1.20:8003"


def test_a_relative_workdir_is_relative_to_the_config_folder(config):
    three(config)
    config.machine("pi", workdir="runtime")
    assert config.host("pi").workdir == (config.paths.root / "runtime").resolve()


def test_a_machine_without_a_file_uses_the_defaults(config):
    host = three(config).host("pi")
    assert host.python is None and host.workdir == Path("~/oblivion").expanduser()


def test_a_wrong_machine_file_says_what_is_wrong(config):
    three(config)
    config.machine("pi", os="amiga")
    with pytest.raises(DeployError, match="os must be one of auto, windows, linux, raspberry"):
        config.host("pi")
    (config.paths.machines / "pi.toml").write_text('[host]\ncolour = "red"\n')
    with pytest.raises(DeployError, match="unknown key"):
        config.host("pi")


def test_a_plan_of_a_machine_needs_nothing_but_the_layout(config):
    three(config)
    service = new_deployment_service(config.host("server"), config.catalogue, shell=Shell(dry_run=True))
    text = "\n".join(service.plan_lines(None))
    assert "machine server: " in text and "bind 127.0.0.1" in text
    assert "MICROPHONE_BASE_URL=http://192.168.1.20:8000" in text and "remote stepper" in text


# --------------------------------------------------------------------------- the commands


def test_the_topology_command_shows_every_machine_and_what_it_exposes(config, capsys):
    three(with_catalogue(config))
    assert cli.main(["topology", "--config", str(config.paths.root)]) == 0
    out = capsys.readouterr().out
    assert "3 machine(s)" in out and "pc  192.168.1.20   bind 0.0.0.0" in out
    assert "runs   microphone port 8000  <- called from other machines" in out
    assert "calls  speaker    http://192.168.1.20:8003" in out and out.rstrip().endswith("OK")


def test_the_topology_command_fails_when_a_machine_cannot_find_what_it_needs(config, capsys):
    three(with_catalogue(config), machines={**THREE, "pc": ["microphone"]})
    assert cli.main(["topology", "--config", str(config.paths.root)]) == 1
    out = capsys.readouterr().out
    assert "ERROR  brain needs 'speaker'" in out and "1 error(s)" in out
    assert "not placed on any machine: camera, speaker" in out  # ...and it says which one is missing


def test_the_topology_command_without_a_robot_file_says_how_to_make_one(config, capsys):
    with_catalogue(config)
    assert cli.main(["topology", "--config", str(config.paths.root)]) == 2
    assert "robot.example.toml" in capsys.readouterr().err


def test_the_ordinary_commands_take_a_machine_name_and_a_config_folder(config, capsys):
    three(with_catalogue(config))
    root = str(config.paths.root)
    assert cli.main(["validate", "--host", "pc", "--config", root]) == 0
    assert cli.main(["plan", "--host", "pi", "--config", root, "--service", "stepper"]) == 0
    assert "SERVICE_HOST=0.0.0.0" in capsys.readouterr().out


def test_the_boot_start_of_a_machine_names_the_machine_and_the_config_folder(config):
    host = three(config).host("pc")
    command = autostart._cli_command(host, "start")
    assert command[-4:] == ["--host", "pc", "--config", str(config.paths.root.resolve())]
    assert Path(command[1]).name == "main.py"
    assert "pc" in autostart.systemd_unit(host)


def test_the_layouts_command_lists_every_layout_and_marks_the_one_in_use(capsys):
    assert cli.main(["layouts"]) == 0
    out = capsys.readouterr().out
    for name in ("all-in-one", "speaker-on-pc", "audio-on-pc", "stepper-on-pi", "pc-server-pi"):
        assert name in out
    assert "speaker    brain" not in out and "pc       speaker" in out  # the machines and their services are shown


def test_the_layouts_command_says_which_layout_robot_toml_uses(config, capsys):
    three(with_catalogue(config))
    assert cli.main(["layouts", "--config", str(config.paths.root)]) == 0
    assert "In use: 'test' (config/robot.toml)" in capsys.readouterr().out


def test_init_writes_robot_toml_for_a_layout_and_refuses_to_overwrite_it(config, capsys):
    shutil.copytree(ROOT / "config" / "layouts", config.paths.layouts)
    with_catalogue(config)
    root = str(config.paths.root)
    args = ["init", "--config", root, "--layout", "speaker-on-pc", "--address", "pc=192.168.1.8", "--address", "pi=192.168.1.197"]
    assert cli.main(args) == 0
    assert "pi       192.168.1.197    brain, microphone, stt, tts, ai-agent, stepper" in capsys.readouterr().out
    text = config.paths.robot.read_text()
    assert 'layout = "speaker-on-pc"' in text and 'pc = "192.168.1.8"' in text
    assert cli.main(args) == 2 and "already exists" in capsys.readouterr().err
    assert cli.main([*args, "--force"]) == 0


def test_init_leaves_nothing_behind_when_an_address_is_missing(config, capsys):
    shutil.copytree(ROOT / "config" / "layouts", config.paths.layouts)
    with_catalogue(config)
    assert cli.main(["init", "--config", str(config.paths.root), "--layout", "speaker-on-pc", "--address", "pc=192.168.1.8"]) == 2
    assert "machine 'pi' of layout 'speaker-on-pc' has no address" in capsys.readouterr().err
    assert not config.paths.robot.exists()


def test_a_single_machine_layout_needs_no_address(config, capsys):
    shutil.copytree(ROOT / "config" / "layouts", config.paths.layouts)
    with_catalogue(config)
    assert cli.main(["init", "--config", str(config.paths.root), "--layout", "all-in-one"]) == 0
    assert config.host("robot").bind == "127.0.0.1"


# --------------------------------------------------------------------------- what ships


def test_the_shipped_robot_example_is_a_valid_single_machine_layout(tmp_path, catalogue):
    config = Config(tmp_path, catalogue)
    shutil.copytree(ROOT / "config" / "layouts", config.paths.layouts)
    shutil.copy(ROOT / "config" / "robot.example.toml", config.paths.robot)
    host = config.host("robot")
    assert sorted(host.services) == sorted(catalogue.services)
    assert validate_host(host)[0] == []


def test_a_real_robot_file_and_your_local_settings_are_never_committed_but_the_examples_are():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    patterns = [line.strip() for line in ignored.splitlines() if line.strip() and not line.startswith("#")]
    assert "/config/robot.toml" in patterns
    assert "/config/local/*" in patterns and "!/config/local/*.example.toml" in patterns
    assert "/config/machines/*.toml" in patterns and "!/config/machines/*.example.toml" in patterns
    assert "robot.example.toml" not in patterns and "/config/layouts/" not in patterns and "/config/services/" not in patterns


@pytest.mark.parametrize("doc", ["docs/DEPLOYMENT.md", "docs/USER_GUIDE.md"])
def test_the_ports_the_docs_print_are_the_ones_of_the_catalogue(catalogue, doc):
    """A port is defined once, in config/catalogue.toml. Wherever the docs repeat it in a service table, it must agree."""
    text = (ROOT / doc).read_text(encoding="utf-8")
    for name, spec in catalogue.services.items():
        rows = [line for line in text.splitlines() if re.match(rf"^\| `?{re.escape(name)}`? \|", line) and re.search(r"\b\d{4}\b", line)]
        assert rows, f"{doc} has no table row with a port for {name}"
        assert all(re.search(rf"\b{spec.port}\b", row) for row in rows), f"{doc}: {name} is not on port {spec.port} in: {rows}"
