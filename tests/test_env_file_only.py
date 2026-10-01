"""Settings live in the .env file only: the runner for services that cannot read one, Docker, the file format."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

import pytest
from conftest import free_port
from dotenv import dotenv_values

from oblivion import runtime
from oblivion.config import load_host, load_registry
from oblivion.envfile import parse_env, render
from oblivion.envparse import render_value
from oblivion.manager import Manager
from oblivion.shell import Shell

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "oblivion" / "service_runner.py"
WORKSPACE = ROOT.parent


@pytest.fixture(scope="module")
def registry():
    return load_registry(ROOT / "services.toml")


def host_for(tmp_path: Path, registry, body: str):
    path = tmp_path / "h.toml"
    path.write_text(textwrap.dedent(body).replace("WORKDIR", (tmp_path / "work").as_posix()))
    return load_host(str(path), registry)


# --------------------------------------------------------------------------- the file format


TRICKY = [
    "plain", "", "http://127.0.0.1:8001", '{"stepper_1": {"step": 17, "dir": 27, "en": 5}}', "/control/{stepper_id}/rotate",
    "value # not a comment", "#leading", "a$b", "cost $5", "  padded  ", "'single'", '"double"', "it's",
    "it's # tricky", 'say "hi" # there', "C:\\Users\\me\\x", "a=b", "línea ünï", "two\nlines",
]


@pytest.mark.parametrize("value", TRICKY)
def test_every_value_is_read_back_identically_by_dotenv_and_by_the_tool(value):
    text = render({"KEY": value, "NEXT": "after"}, "h")
    assert dotenv_values(stream=__import__("io").StringIO(text)) == {"KEY": value, "NEXT": "after"}  # python-dotenv
    assert parse_env(text) == {"KEY": value, "NEXT": "after"}  # the runner and the tool
    assert "\n" not in render_value(value)  # one line per variable, so Brain's line-based reader copes too


def test_plain_values_are_not_quoted():
    assert render_value("http://h:1") == "http://h:1"
    assert render_value('{"a": {"b": 1}}') == '{"a": {"b": 1}}'


# --------------------------------------------------------------------------- service_runner.py


def run_runner(tmp_path: Path, env_text: str, *, extra_env: dict[str, str] | None = None, service_files: dict[str, str] | None = None):
    service = tmp_path / "service"
    service.mkdir(exist_ok=True)
    (service / "main.py").write_text(textwrap.dedent("""
        import json, os, sys
        import config                      # the SERVICE's own module, not one of the tool's
        out = {"name": __name__, "argv": sys.argv[1:], "path0": sys.path[0], "config": config.WHO,
               "tool_modules": sorted(m for m in sys.modules if m == "oblivion" or m.startswith("oblivion.")),
               "env": {k: v for k, v in os.environ.items() if k.startswith("T_")}}
        open(os.environ["T_OUT"], "w").write(json.dumps(out))
    """))
    (service / "config.py").write_text('WHO = "service"\n')
    for name, text in (service_files or {}).items():
        (service / name).write_text(text)
    env_file = tmp_path / "svc.env"
    env_file.write_text(env_text, encoding="utf-8")
    out = tmp_path / "out.json"
    import os
    env = {**os.environ, "T_OUT": str(out), **(extra_env or {})}
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--env-file", str(env_file), "--", str(service / "main.py"), "extra-arg"],
        cwd=service, env=env, capture_output=True, text=True, check=False,
    )
    return result, (json.loads(out.read_text()) if out.exists() else None), service


def test_the_runner_loads_the_file_and_runs_the_service_exactly_like_python_main_py(tmp_path):
    result, out, service = run_runner(tmp_path, "T_ONE=1\nT_TWO='a # b'\nT_THREE=\"x\\\"y\"\n")
    assert result.returncode == 0, result.stderr
    assert out["env"]["T_ONE"] == "1" and out["env"]["T_TWO"] == "a # b" and out["env"]["T_THREE"] == 'x"y'
    assert out["name"] == "__main__" and out["argv"] == ["extra-arg"]
    assert Path(out["path0"]) == service.resolve()
    assert out["config"] == "service"  # the tool's own config.py never shadows the service's modules
    assert out["tool_modules"] == []  # nothing of the tool is left in the service's process


def test_a_variable_that_is_already_set_wins_like_it_does_with_dotenv(tmp_path):
    result, out, _ = run_runner(tmp_path, "T_ONE=file\nT_TWO=file\n", extra_env={"T_ONE": "already-set"})
    assert result.returncode == 0, result.stderr
    assert (out["env"]["T_ONE"], out["env"]["T_TWO"]) == ("already-set", "file")


def test_a_missing_env_file_stops_the_service_with_a_clear_message(tmp_path):
    env_file = tmp_path / "nope.env"
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--env-file", str(env_file), "--", str(tmp_path / "main.py")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2 and "does not exist" in result.stderr


# --------------------------------------------------------------------------- native start of a service without dotenv


def test_the_microphone_gets_its_settings_from_the_file_through_the_runner(registry, tmp_path, monkeypatch):
    """microphone_microservice has no dotenv support; it is started by the runner, with nothing in its environment."""
    monkeypatch.setenv("OBLIVION_CONSOLE", "0")
    host = host_for(tmp_path, registry, '[host]\nos = "linux"\nworkdir = "WORKDIR"\n[services.microphone]\n')
    assert registry.services["microphone"].dotenv is False and registry.services["brain"].dotenv is True
    service_dir = host.service_dir("microphone")
    service_dir.mkdir(parents=True)
    port = free_port()
    (service_dir / "main.py").write_text(textwrap.dedent("""
        import json, os
        from http.server import BaseHTTPRequestHandler, HTTPServer
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                body = json.dumps({"keywords": os.environ.get("MICROPHONE_TARGET_KEYWORDS"), "data": {"is_available": True}}).encode()
                self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(body)
        HTTPServer(("127.0.0.1", int(os.environ["SERVICE_PORT"])), H).serve_forever()
    """))
    manager = Manager(Shell(echo=False), host, registry)
    env_file = manager.env_target("microphone")
    env_file.write_text(render({"SERVICE_HOST": "127.0.0.1", "SERVICE_PORT": str(port), "MICROPHONE_TARGET_KEYWORDS": "usb # mic"}, "h"))
    monkeypatch.setenv("MICROPHONE_TARGET_KEYWORDS", "from-the-shell")  # must not beat the file
    monkeypatch.setattr(Shell, "python_of", lambda self, venv: Path(sys.executable))
    try:
        runtime.native_start(Shell(echo=False), host, "microphone", parse_env(env_file.read_text()), env_file)
        deadline = time.monotonic() + 15
        answer = None
        while time.monotonic() < deadline and answer is None:
            try:
                answer = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).read())
            except OSError:
                time.sleep(0.2)
        assert answer is not None, "the microphone stand-in never came up"
        assert answer["keywords"] == "usb # mic"
    finally:
        runtime.native_stop(Shell(echo=False), host, "microphone")


def test_the_start_command_shows_the_runner_only_for_services_that_need_it(registry, tmp_path, capsys):
    host = host_for(tmp_path, registry, '[host]\nos = "linux"\nworkdir = "WORKDIR"\n[services.microphone]\n[services.tts]\n')
    for name in ("microphone", "tts"):
        runtime.native_start(Shell(dry_run=True), host, name, {}, host.workdir / f"{name}.env")
    lines = capsys.readouterr().out.splitlines()
    assert "service_runner.py --env-file" in lines[0] and "microphone_microservice" in lines[0]
    assert "service_runner.py" not in lines[1] and "tts_microservice" in lines[1]


# --------------------------------------------------------------------------- what a service inherits


def test_the_child_environment_drops_what_the_file_defines_and_keeps_the_rest(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "exported-in-the-shell")
    monkeypatch.setenv("UNRELATED_SETTING", "kept")
    env = runtime.child_environment({"GROQ_API_KEY": "x", "SERVICE_PORT": "1"})
    assert "GROQ_API_KEY" not in env and env["UNRELATED_SETTING"] == "kept" and env["PYTHONUNBUFFERED"] == "1"
    assert "PATH" in {k.upper() for k in env}  # the interpreter still finds what it needs


@pytest.mark.skipif(sys.platform != "win32", reason="Windows variable names are case-insensitive")
def test_on_windows_a_differently_cased_variable_is_dropped_too(monkeypatch):
    monkeypatch.setenv("Groq_Api_Key", "x")
    assert not [k for k in runtime.child_environment({"GROQ_API_KEY": "y"}) if k.upper() == "GROQ_API_KEY"]


# --------------------------------------------------------------------------- the console format


def test_the_readable_console_format_is_a_value_of_the_file_not_an_injected_variable(registry, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "uses_console_window", lambda: True)
    host = host_for(tmp_path, registry, """
        [host]
        workdir = "WORKDIR"
        [services.tts]
        [services.speaker]
        [services.speaker.env]
        LOG_FORMAT = "json"
    """)
    manager = Manager(Shell(dry_run=True), host, registry)
    tts = manager.resolve("tts")
    assert tts.values["LOG_FORMAT"] == "console" and tts.layer_of["LOG_FORMAT"] == "computed"
    assert manager.resolve("speaker").values["LOG_FORMAT"] == "json"  # the operator's choice wins
    monkeypatch.setattr(runtime, "uses_console_window", lambda: False)
    assert "LOG_FORMAT" not in manager.resolve("tts").values


# --------------------------------------------------------------------------- Docker


def docker_run_line(host, name: str, capsys) -> str:
    runtime.docker_start(Shell(dry_run=True), host, name, host.workdir / "env" / f"{name}.env")
    return next(line for line in capsys.readouterr().out.splitlines() if "docker run" in line)


def test_a_container_gets_the_env_file_mounted_and_no_variables(registry, tmp_path, capsys):
    host = host_for(tmp_path, registry, '[host]\nos = "linux"\nworkdir = "WORKDIR"\n[services.tts]\nruntime = "docker"\n')
    line = docker_run_line(host, "tts", capsys)
    assert "--mount type=bind," in line and "target=/app/.env,readonly" in line and "tts.env" in line
    assert "--env-file" not in line and " -e " not in line


def test_a_container_of_a_service_that_cannot_read_a_file_still_gets_its_settings(registry, tmp_path, capsys):
    host = host_for(tmp_path, registry, '[host]\nos = "linux"\nworkdir = "WORKDIR"\n[services.microphone]\nruntime = "docker"\n')
    line = docker_run_line(host, "microphone", capsys)
    assert "--env-file" in line and "--mount" not in line  # documented exception until microphone reads a .env


# --------------------------------------------------------------------------- the registry follows the services


@pytest.mark.parametrize("service,folder", [
    ("brain", "brain_microservice"), ("microphone", "microphone_microservice"), ("stt", "stt_microservice"),
    ("tts", "tts_microservice"), ("speaker", "speaker_microservice"), ("stepper", "stepper_microservice"), ("ai-agent", "ai-agent"),
])
def test_the_dotenv_flag_of_every_service_matches_what_its_source_does(registry, service, folder):
    source = WORKSPACE / folder
    if not source.exists():
        pytest.skip("no workspace next to this repository")
    skipped = {"windows", "vendor", "tests", "testclear", "__pycache__", ".git", "old"}
    reads_dotenv = any(
        "load_dotenv" in path.read_text(encoding="utf-8", errors="ignore")
        for path in source.rglob("*.py")
        if not skipped & set(path.relative_to(source).parts)
    )
    assert registry.services[service].dotenv == reads_dotenv, (
        f"{service}: its code {'reads' if reads_dotenv else 'does not read'} a .env; set dotenv = {str(reads_dotenv).lower()} in services.toml"
    )


def test_a_value_python_dotenv_would_expand_is_refused_with_a_clear_message(registry, tmp_path):
    from oblivion.envfile import resolve_env
    secrets = tmp_path / "s.env"
    secrets.write_text("TTS__SOME_SECRET=abc${HOME}def\nTTS__FINE=cost $5\n")
    host = host_for(tmp_path, registry, f'[host]\nsecrets = "{secrets.as_posix()}"\n[services.tts]\n')
    (error,) = resolve_env(host, "tts", None).errors
    assert "SOME_SECRET" in error and "expand" in error
