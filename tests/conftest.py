"""Fixtures: a fake platform of real git repositories served from local bare remotes."""

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


def write_registry(base: Path, remotes: dict[str, FakeRemote], ports: dict[str, int]) -> Path:
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
    path = base / "services.toml"
    path.write_text("\n".join(body))
    return path
