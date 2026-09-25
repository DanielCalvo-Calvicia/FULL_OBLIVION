"""tee.py copies a service's output to the console and the log file, and forgets the pid when it ends."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TEE = Path(__file__).resolve().parent.parent / "oblivion" / "tee.py"


def _run(tmp_path: Path, *command: str) -> tuple[subprocess.CompletedProcess, Path, Path]:
    log, pid_file = tmp_path / "svc.log", tmp_path / "svc.pid"
    result = subprocess.run(
        [sys.executable, str(TEE), "--name", "svc", "--log", str(log), "--pid-file", str(pid_file), "--", *command],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False, timeout=60,
    )
    return result, log, pid_file


def test_output_goes_to_console_and_log_and_exit_code_is_kept(tmp_path):
    code = "import sys; print('hello out'); print('boom err', file=sys.stderr); sys.exit(3)"
    result, log, _ = _run(tmp_path, sys.executable, "-c", code)
    assert result.returncode == 3
    for text in (result.stdout, log.read_text()):
        assert "hello out" in text and "boom err" in text and "exited with code 3" in text


def test_pid_file_is_removed_only_when_it_is_the_wrappers_own(tmp_path):
    pid_file = tmp_path / "svc.pid"
    pid_file.write_text("1")  # someone else's pid: must stay
    _run(tmp_path, sys.executable, "-c", "pass")
    assert pid_file.exists()
    assert os.getpid()  # sanity


def test_unstartable_command_is_reported(tmp_path):
    result, log, _ = _run(tmp_path, str(tmp_path / "does-not-exist"))
    assert result.returncode == 127
    assert "could not start svc" in log.read_text()


def test_console_shows_only_errors_and_stream_events_but_the_log_keeps_everything(tmp_path):
    code = (
        "print('2026-09-20T10:00:00.000+00:00 INFO     service=b logger=x message=\"Request received\"');"
        "print('2026-09-20T10:00:01.000+00:00 INFO     service=b logger=x message=\"stream event\" "
        "stream_stage=\"mic->brain\" stream_event={\"type\":\"partial\"}');"
        "print('2026-09-20T10:00:02.000+00:00 ERROR    service=b logger=x message=\"boom\"');"
        "print('2026-09-20T10:00:03.000+00:00 WARNING  service=b logger=x message=\"careful\"');"
        "print('Traceback (most recent call last):')"
    )
    script = tmp_path / "emit.py"
    script.write_text(code.replace(");", ");\n"))
    result, log, _ = _run(tmp_path, sys.executable, str(script))
    for hidden in ("Request received", "careful"):
        assert hidden not in result.stdout
        assert hidden in log.read_text()
    for shown in ("stream_stage=", 'message="boom"', "Traceback (most recent call last)"):
        assert shown in result.stdout


def test_filter_can_be_switched_off(monkeypatch, tmp_path):
    monkeypatch.setenv("OBLIVION_CONSOLE_FILTER", "all")
    line = "2026-09-20T10:00:00.000+00:00 INFO     service=b logger=x message=\"Request received\""
    result, _, _ = _run(tmp_path, sys.executable, "-c", f"print({line!r})")
    assert "Request received" in result.stdout


def test_json_records_are_filtered_the_same_way():
    from importlib import util

    spec = util.spec_from_file_location("tee", TEE)
    tee = util.module_from_spec(spec)
    spec.loader.exec_module(tee)
    assert not tee.show_on_console('{"level":"INFO","message":"x"}', "stream")
    assert tee.show_on_console('{"level":"ERROR","message":"x"}', "stream")
    assert tee.show_on_console('{"level":"INFO","stream_stage":"a->b"}', "stream")


def test_errors_mode_hides_stream_events_too(monkeypatch, tmp_path):
    monkeypatch.setenv("OBLIVION_CONSOLE_FILTER", "errors")
    script = tmp_path / "emit.py"
    script.write_text(
        'print(\'2026-09-20T10:00:01.000+00:00 INFO     service=b logger=x message="stream event" '
        'stream_stage="mic->brain"\')\n'
        'print(\'2026-09-20T10:00:02.000+00:00 ERROR    service=b logger=x message="boom"\')\n'
        'print(\'{"level":"INFO","stream_stage":"a->b"}\')\n'
    )
    result, log, _ = _run(tmp_path, sys.executable, str(script))
    assert 'message="boom"' in result.stdout and "errors only" in result.stdout
    assert "stream_stage" not in result.stdout.split("errors only", 1)[1]
    assert "stream_stage" in log.read_text()
