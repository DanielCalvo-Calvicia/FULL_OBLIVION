"""Booting the Brain machine before the machines it depends on: Brain exits when its preflight times out and
nothing restarts it, so the tool waits (bounded) for the required remote services before starting it."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from conftest import free_port

from oblivion import manager as manager_module
from oblivion.config import load_host, load_registry
from oblivion.manager import Manager, Options
from oblivion.shell import Shell

ROOT = Path(__file__).resolve().parent.parent
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


class Machine:
    """A stand-in for another machine: answers /health and /available on one port once it is 'booted'."""

    def __init__(self) -> None:
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
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
    m = Machine()
    yield m
    m.stop()


@pytest.fixture(autouse=True)
def _fast_polling(monkeypatch):
    monkeypatch.setattr(manager_module, "REMOTE_POLL_SECONDS", 0.2)


def brain_manager(tmp_path: Path, url: str, *, wait: float, dry_run: bool = False, extra: str = "") -> Manager:
    registry = load_registry(ROOT / "services.toml")
    path = tmp_path / "brain-machine.toml"
    remotes = "".join(f'{name} = "{url}"\n' for name in REMOTES)
    path.write_text(f'[host]\nos = "linux"\nworkdir = "{(tmp_path / "work").as_posix()}"\n[services.brain]\n[remote]\n{remotes}{extra}')
    return Manager(Shell(dry_run=dry_run), load_host(str(path), registry), registry, Options(remote_wait=wait))


def test_it_waits_until_the_other_machine_is_up_and_then_carries_on(tmp_path, machine, capsys):
    machine.boot_after(1.0)
    started = time.monotonic()
    brain_manager(tmp_path, machine.url, wait=20).wait_for_remotes("brain")
    assert 0.8 <= time.monotonic() - started < 15
    out = capsys.readouterr().out
    assert "waiting up to 20s" in out
    assert all(f"{name} is up" in out for name in REMOTES)
    assert "warning" not in out


def test_a_machine_that_never_comes_up_is_a_warning_after_the_wait_not_an_error(tmp_path, machine, capsys):
    started = time.monotonic()
    brain_manager(tmp_path, machine.url, wait=1.0).wait_for_remotes("brain")  # nothing listens on that port
    assert 0.9 <= time.monotonic() - started < 8
    out = capsys.readouterr().out
    assert out.count("is not reachable yet; starting anyway") == len(REMOTES)


def test_a_wait_of_zero_never_waits(tmp_path, machine, capsys):
    started = time.monotonic()
    brain_manager(tmp_path, machine.url, wait=0).wait_for_remotes("brain")
    assert time.monotonic() - started < 0.5
    assert capsys.readouterr().out == ""


def test_the_optional_stepper_is_not_waited_for(tmp_path, machine, capsys):
    machine.boot()
    extra = f'stepper = "http://127.0.0.1:{free_port()}"\n'  # its machine is off; Brain runs fine without it
    started = time.monotonic()
    brain_manager(tmp_path, machine.url, wait=30, extra=extra).wait_for_remotes("brain")
    assert time.monotonic() - started < 10
    assert "stepper" not in capsys.readouterr().out


def test_a_dry_run_does_not_wait(tmp_path, machine, capsys):
    brain_manager(tmp_path, machine.url, wait=30, dry_run=True).wait_for_remotes("brain")
    assert capsys.readouterr().out == ""


def test_services_with_everything_local_are_unaffected(tmp_path, capsys):
    registry = load_registry(ROOT / "services.toml")
    path = tmp_path / "all.toml"
    path.write_text(f'[host]\nworkdir = "{(tmp_path / "w").as_posix()}"\n' + "".join(f"[services.{n}]\n" for n in (*REMOTES, "brain")))
    Manager(Shell(), load_host(str(path), registry), registry, Options(remote_wait=30)).wait_for_remotes("brain")
    assert capsys.readouterr().out == ""
