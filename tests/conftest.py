"""Fixtures: a fake platform of real git repositories served from local bare remotes, and helpers that write a config/ folder."""

from __future__ import annotations

import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _headless(monkeypatch):
    """Never pop console windows from tests."""
    monkeypatch.setenv("OBLIVION_CONSOLE", "0")

SERVICE_MAIN = '''
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
def _mine(k): return k.startswith("T_") or k in ("SERVICE_HOST", "SERVICE_PORT", "PRODUCER_BASE_URL")
# What the process was STARTED with: the deploy tool must not have put any setting in it.
STARTED_WITH = sorted(k for k in os.environ if _mine(k))
# What python-dotenv does in the real services: read the .env next to the code; a variable already set wins.
for _line in open(os.path.join(os.path.dirname(__file__), ".env"), encoding="utf-8"):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _key, _, _value = _line.partition("=")
        os.environ.setdefault(_key, _value)
VERSION = open(os.path.join(os.path.dirname(__file__), "VERSION")).read().strip()
if VERSION == "broken":
    raise SystemExit("this release crashes on start")

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = {"/health": {}, "/available": {"data": {"is_available": True, "reason": None}},
                "/version": {"version": VERSION, "started_with": STARTED_WITH, "env": {k: v for k, v in os.environ.items() if k.startswith("T_") or k.endswith("_BASE_URL")}}}
        if self.path not in body:
            self.send_response(404); self.end_headers(); return
        raw = json.dumps(body[self.path]).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(raw)

HTTPServer((os.environ.get("SERVICE_HOST", "127.0.0.1"), int(os.environ["SERVICE_PORT"])), Handler).serve_forever()
'''


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
                            env={**__import__("os").environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    return result.stdout.strip()


class FakeRemote:
    """A bare 'GitHub' repository plus a working copy to push new versions from."""

    def __init__(self, base: Path, name: str, env_example: str = "T_DEFAULT=from-example\n") -> None:
        self.bare = base / f"{name}.git"
        self.work = base / f"{name}-work"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.bare)], check=True, capture_output=True)
        subprocess.run(["git", "clone", "-q", str(self.bare), str(self.work)], check=True, capture_output=True)
        git(self.work, "checkout", "-q", "-b", "main")
        (self.work / "main.py").write_text(SERVICE_MAIN)
        (self.work / ".env.example").write_text(env_example)
        for family in ("windows", "linux"):
            (self.work / f"requirements.{family}.txt").write_text("# no dependencies\n-e ../shared-logging\n")
        self.release("v1")

    @property
    def url(self) -> str:
        return str(self.bare)

    def release(self, version: str, branch: str = "main") -> str:
        try:
            current = git(self.work, "rev-parse", "--abbrev-ref", "HEAD")
        except subprocess.CalledProcessError:  # no commit yet
            current = branch
        if branch != current:
            try:
                git(self.work, "checkout", "-q", branch)
            except subprocess.CalledProcessError:
                git(self.work, "checkout", "-q", "-b", branch)
        (self.work / "VERSION").write_text(version)
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", version)
        git(self.work, "push", "-q", "origin", branch)
        return git(self.work, "rev-parse", "HEAD")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def write_catalogue(base: Path, remotes: dict[str, FakeRemote], ports: dict[str, int]) -> "ConfigPaths":
    """``<base>/config/catalogue.toml`` for fake services (``consumer`` calls ``producer``); returns the config paths."""
    from infrastructure.config.paths import ConfigPaths

    body = ['[libraries.shared-logging]', 'wheel_dir = "nowhere"', ""]
    for name, remote in remotes.items():
        body.append(textwrap.dedent(f'''
            [services.{name}]
            git = "{remote.url.replace(chr(92), "/")}"
            branch = "main"
            port = {ports[name]}
            ready = "/available"
            requirements = {{ windows = "requirements.windows.txt", linux = "requirements.linux.txt" }}
            {"consumes = { producer = " + '"PRODUCER_BASE_URL"' + " }" if name == "consumer" else ""}
        '''))
    paths = ConfigPaths(base / "config")
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.catalogue.write_text("\n".join(body))
    return paths


def write_layout(
    paths: "ConfigPaths",
    machines: dict[str, list[str]],
    addresses: dict[str, str] | None = None,
    *,
    name: str = "test",
    in_layout: dict[str, str] | None = None,
    ports: dict[str, dict[str, int]] | None = None,
) -> None:
    """``config/robot.toml`` choosing a layout, and the layout ``config/layouts/<name>.toml`` itself.

    ``addresses`` go under [addresses] of robot.toml; ``in_layout`` are default addresses written in the layout file.
    """
    paths.layouts.mkdir(parents=True, exist_ok=True)
    layout = ["description = 'a test layout'"]
    for machine, services in machines.items():
        layout.append(f"[machines.{machine}]")
        if in_layout and machine in in_layout:
            layout.append(f'address = "{in_layout[machine]}"')
        layout.append("services = [" + ", ".join(f'"{s}"' for s in services) + "]")
        machine_ports = (ports or {}).get(machine, {})
        if machine_ports:
            layout.append("ports = { " + ", ".join(f"{s} = {p}" for s, p in machine_ports.items()) + " }")
    paths.layout_file(name).write_text("\n".join(layout) + "\n")
    robot = [f'layout = "{name}"', "[addresses]"] + [f'{m} = "{a}"' for m, a in (addresses or {}).items()]
    paths.robot.write_text("\n".join(robot) + "\n")


def write_settings(paths: "ConfigPaths", folder: str, name: str, text: str) -> Path:
    """``config/<folder>/<name>.toml`` (folder: ``services`` or ``local``)."""
    target = paths.root / folder / f"{name}.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(text).lstrip("\n"))
    return target


def write_machine(paths: "ConfigPaths", machine: str, **host: object) -> Path:
    """``config/machines/<machine>.toml`` with a [host] table (os, workdir, python, bind)."""
    paths.machines.mkdir(parents=True, exist_ok=True)
    lines = ["[host]"] + [f"{k} = {_toml(v)}" for k, v in host.items()]
    target = paths.machine_file(machine)
    target.write_text("\n".join(lines) + "\n")
    return target


def _toml(value: object) -> str:
    if isinstance(value, Path):
        return '"' + value.as_posix() + '"'
    if isinstance(value, str):
        return '"' + value.replace("\\", "/") + '"'
    return str(value)


# --------------------------------------------------------------------------- a temporary config/ folder


class Config:
    """A temporary ``config/`` folder for one test, built with a few calls, and the host loaded from it.

        cfg = Config(tmp_path, catalogue).layout({"m": ["stt", "tts"]}).local("stt", 'STT_ENGINE = "local"')
        host = cfg.host("m")
    """

    def __init__(self, base: Path, catalogue) -> None:
        from infrastructure.config.paths import ConfigPaths

        self.base = base
        self.catalogue = catalogue
        self.paths = ConfigPaths(base / "config")
        self.paths.root.mkdir(parents=True, exist_ok=True)

    def layout(self, machines, addresses=None, **kwargs) -> "Config":
        """Single-machine layouts get 127.0.0.1 unless ``addresses`` says otherwise."""
        in_layout = {m: "127.0.0.1" for m in machines} if addresses is None and len(machines) == 1 else None
        write_layout(self.paths, machines, addresses, in_layout=in_layout, **kwargs)
        return self

    def raw_layout(self, text: str, addresses: dict[str, str] | None = None, name: str = "test") -> "Config":
        """A layout file exactly as written (for the mistakes the helpers would not let you make), and a robot.toml for it."""
        self.paths.layouts.mkdir(parents=True, exist_ok=True)
        self.paths.layout_file(name).write_text(textwrap.dedent(text))
        robot = [f'layout = "{name}"', "[addresses]"] + [f'{m} = "{a}"' for m, a in (addresses or {}).items()]
        self.paths.robot.write_text("\n".join(robot) + "\n")
        return self

    def service(self, name: str, text: str) -> "Config":
        """``config/services/<name>.toml``: pass the body, e.g. ``'branch = "x"'`` or ``'[env]\nA = 1'``."""
        write_settings(self.paths, "services", name, text)
        return self

    def local(self, name: str, text: str) -> "Config":
        write_settings(self.paths, "local", name, text)
        return self

    def env(self, name: str, **values) -> "Config":
        """``config/local/<name>.toml`` with an [env] table."""
        body = "[env]\n" + "\n".join(f"{k} = {_toml(v)}" for k, v in values.items())
        return self.local(name, body)

    def machine(self, name: str, **host) -> "Config":
        write_machine(self.paths, name, **host)
        return self

    def host(self, machine: str = "robot"):
        from infrastructure.config.host_loader import load_host

        return load_host(machine, self.catalogue, self.paths)


@pytest.fixture(scope="session")
def catalogue():
    """The shipped catalogue (the real services), loaded once."""
    from infrastructure.config.catalogue_loader import load_catalogue
    from infrastructure.config.paths import ConfigPaths

    return load_catalogue(ConfigPaths())


@pytest.fixture
def config(tmp_path, catalogue):
    return Config(tmp_path, catalogue)


ALL_SERVICES = ["brain", "microphone", "stt", "tts", "speaker", "ai-agent", "stepper"]


def shipped_layout_hosts(base: Path, catalogue):
    """``(layout name, machine name, Host)`` for every machine of every layout shipped in config/layouts/, with made-up addresses."""
    import shutil

    from infrastructure.config.paths import ConfigPaths

    layouts = sorted(ConfigPaths().layouts.glob("*.toml"))
    assert layouts, "no layouts shipped"
    for layout in layouts:
        config = Config(base / layout.stem, catalogue)
        config.paths.layouts.mkdir(parents=True)
        shutil.copy(layout, config.paths.layouts / layout.name)
        machines = [line.split("]")[0].split(".", 1)[1] for line in layout.read_text().splitlines() if line.startswith("[machines.")]
        config.paths.robot.write_text(f'layout = "{layout.stem}"\n[addresses]\n' + "".join(f'{m} = "192.168.1.50"\n' for m in machines))
        for machine in machines:
            yield layout.stem, machine, config.host(machine)
