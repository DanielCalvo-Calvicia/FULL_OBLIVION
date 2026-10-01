"""The ``prepare`` step: a service script run after its .env is written (tts uses it to fetch the Piper voice)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import git
from test_deploy_flow import Platform

from oblivion import runtime
from oblivion.config import DeployError, load_registry
from oblivion.shell import Shell

PREPARE_SCRIPT = '''
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(here, "FAIL_PREPARE")):
    print("download failed: no network", file=sys.stderr)
    sys.exit(1)
with open(os.path.join(here, ".env"), encoding="utf-8") as env:
    seen = env.read()
with open(os.path.join(here, "prepared.txt"), "w", encoding="utf-8") as out:
    out.write(seen)
'''


class PreparePlatform(Platform):
    """The producer service has ``prepare = ["prepare.py"]`` in the catalogue and ships the script."""

    def __init__(self, base: Path) -> None:
        super().__init__(base)
        (self.remotes["producer"].work / "prepare.py").write_text(PREPARE_SCRIPT)
        self.remotes["producer"].release("v1-with-prepare")
        text = self.registry_path.read_text()
        self.registry_path.write_text(text.replace("[services.producer]\n", '[services.producer]\nprepare = ["prepare.py"]\n'))

    @property
    def producer_dir(self) -> Path:
        return self.workdir / "services" / "producer_microservice"


@pytest.fixture
def platform(tmp_path: Path):
    p = PreparePlatform(tmp_path)
    yield p
    try:
        p.manager().stop(None)
    except DeployError:
        pass


def test_the_catalogue_reads_prepare(platform):
    assert load_registry(platform.registry_path).services["producer"].prepare == ("prepare.py",)
    assert load_registry(platform.registry_path).services["consumer"].prepare == ()


def test_deploy_runs_prepare_with_the_service_python_after_the_env_file_is_written(platform):
    assert platform.manager().deploy(["producer"]) == []

    seen = (platform.producer_dir / "prepared.txt").read_text()
    assert "T_MARK=hello" in seen and f"SERVICE_PORT={platform.ports['producer']}" in seen  # the final settings


def test_a_failing_prepare_only_warns_and_the_service_still_comes_up(platform, capsys):
    (platform.remotes["producer"].work / "FAIL_PREPARE").write_text("")
    platform.remotes["producer"].release("v2-prepare-fails")

    assert platform.manager().deploy(["producer"]) == []

    assert "warning: producer: `prepare.py` failed (1)" in capsys.readouterr().out
    assert platform.get("producer", "/version")["version"] == "v2-prepare-fails"
    assert not (platform.producer_dir / "prepared.txt").exists()


def test_update_runs_prepare_again(platform):
    manager = platform.manager()
    assert manager.deploy(["producer"]) == []
    (platform.producer_dir / "prepared.txt").unlink()
    platform.remotes["producer"].release("v3")

    assert platform.manager().update(["producer"]) == []

    assert (platform.producer_dir / "prepared.txt").exists()
    assert git(platform.producer_dir, "rev-parse", "HEAD") == git(platform.remotes["producer"].work, "rev-parse", "HEAD")


def test_dry_run_prints_the_command_and_runs_nothing(platform, capsys):
    manager = platform.manager()
    manager.shell.dry_run = True
    manager.shell.echo = True

    manager.prepare("producer")

    assert "[dry-run]" in capsys.readouterr().out
    assert not (platform.producer_dir / "prepared.txt").exists()


def test_a_service_without_prepare_runs_nothing(platform, capsys):
    platform.manager().prepare("consumer")

    assert capsys.readouterr().out == ""


def test_docker_images_run_prepare_while_building(platform, capsys):
    manager = platform.manager()
    shell = Shell(dry_run=True)

    runtime.docker_build(shell, manager.host, "producer", platform.workdir / "build" / "producer")

    assert "--build-arg PREPARE=prepare.py" in capsys.readouterr().out
