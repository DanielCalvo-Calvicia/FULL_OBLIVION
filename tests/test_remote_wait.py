"""Booting the Brain machine before the machines it depends on: Brain exits when its preflight times out and
nothing restarts it, so the tool waits (bounded) for the required remote services before starting it."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from conftest import ALL_SERVICES, Config, free_port

from application.dtos.options import Options
from application.services import deployment_service
from composition_root.container import new_deployment_service
from infrastructure.outbound.shell.shell import Shell

REMOTES = ("microphone", "stt", "tts", "speaker", "ai-agent")


class _Healthy(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        raw = json.dumps({"data": {"is_available": True}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(raw)


class OtherMachine:
    """A stand-in for another machine: answers /health and /available on one port once it is 'booted'."""

    def __init__(self) -> None:
        self.port = free_port()
        self._server: ThreadingHTTPServer | None = None

    def boot(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), _Healthy)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def boot_after(self, seconds: float) -> None:
        threading.Timer(seconds, self.boot).start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()


@pytest.fixture
def machine():
    m = OtherMachine()
    yield m
    m.stop()


@pytest.fixture(autouse=True)
def _fast_polling(monkeypatch):
    monkeypatch.setattr(deployment_service, "REMOTE_POLL_SECONDS", 0.2)


def brain_service(config: Config, tmp_path: Path, machine: OtherMachine, *, wait: float, dry_run: bool = False, extra: tuple[str, ...] = ()):
    """Brain on machine ``m``; everything it needs on machine ``other``, which answers on ``machine.port`` for every service."""
    services = [*REMOTES, *extra]
    config.layout(
        {"m": ["brain"], "other": services},
        addresses={"m": "127.0.0.1", "other": "127.0.0.1"},
        ports={"other": {name: machine.port for name in REMOTES} | ({"stepper": free_port()} if "stepper" in extra else {})},
    )
    config.machine("m", os="linux", workdir=tmp_path / "work")
    return new_deployment_service(config.host("m"), config.catalogue, Options(remote_wait=wait), shell=Shell(dry_run=dry_run))


def test_it_waits_until_the_other_machine_is_up_and_then_carries_on(config, tmp_path, machine, capsys):
    machine.boot_after(1.0)
    started = time.monotonic()
    brain_service(config, tmp_path, machine, wait=20).wait_for_remotes("brain")
    assert 0.8 <= time.monotonic() - started < 15
    out = capsys.readouterr().out
    assert "waiting up to 20s" in out
    assert all(f"{name} is up" in out for name in REMOTES)
    assert "warning" not in out


def test_a_machine_that_never_comes_up_is_a_warning_after_the_wait_not_an_error(config, tmp_path, machine, capsys):
    started = time.monotonic()
    brain_service(config, tmp_path, machine, wait=1.0).wait_for_remotes("brain")  # nothing listens on that port
    assert 0.9 <= time.monotonic() - started < 8
    out = capsys.readouterr().out
    assert out.count("is not reachable yet; starting anyway") == len(REMOTES)


def test_a_wait_of_zero_never_waits(config, tmp_path, machine, capsys):
    started = time.monotonic()
    brain_service(config, tmp_path, machine, wait=0).wait_for_remotes("brain")
    assert time.monotonic() - started < 0.5
    assert capsys.readouterr().out == ""


def test_the_optional_stepper_is_not_waited_for(config, tmp_path, machine, capsys):
    machine.boot()  # its machine is off, but Brain runs fine without the stepper
    started = time.monotonic()
    brain_service(config, tmp_path, machine, wait=30, extra=("stepper",)).wait_for_remotes("brain")
    assert time.monotonic() - started < 10
    assert "stepper" not in capsys.readouterr().out


def test_a_dry_run_does_not_wait(config, tmp_path, machine, capsys):
    brain_service(config, tmp_path, machine, wait=30, dry_run=True).wait_for_remotes("brain")
    assert capsys.readouterr().out == ""


def test_services_with_everything_local_are_unaffected(config, tmp_path, capsys):
    config.layout({"robot": [*REMOTES, "brain"]}).machine("robot", workdir=tmp_path / "w")
    new_deployment_service(config.host("robot"), config.catalogue, Options(remote_wait=30)).wait_for_remotes("brain")
    assert capsys.readouterr().out == ""
