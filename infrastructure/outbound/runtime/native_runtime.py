"""Running a service as a plain process of this machine (Windows, Linux, Raspberry Pi)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from application.ports.outbound.shell_port import ShellPort
from domain.entities.host import Host

STOP_TIMEOUT_SECONDS = 10.0
RUNNER = Path(__file__).with_name("service_runner.py")
TEE = Path(__file__).with_name("tee.py")


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(host: Host, name: str) -> int | None:
    try:
        return int(host.pid_file(name).read_text().strip())
    except (OSError, ValueError):
        return None


def is_running(host: Host, name: str) -> bool:
    pid = read_pid(host, name)
    return pid is not None and _pid_alive(pid)


def uses_console_window() -> bool:
    """Windows shows each service in its own console window. Set OBLIVION_CONSOLE=0 for headless (tests, CI)."""
    return sys.platform == "win32" and os.environ.get("OBLIVION_CONSOLE", "1") != "0"


def child_environment(settings: dict[str, str]) -> dict[str, str]:
    """The environment a service starts with: this process's, minus every name the service's ``.env`` defines.

    The settings live in the ``.env`` file only, and the services load it with ``override=False`` (a variable that is
    already set wins over the file). So a same-named variable on the machine or in the operator's shell, say an
    exported ``GROQ_API_KEY``, must not reach the service: it would silently beat the file.
    """
    normalise = str.upper if os.name == "nt" else str  # Windows variable names are case-insensitive
    defined = {normalise(key) for key in settings}
    kept = {key: value for key, value in os.environ.items() if normalise(key) not in defined}
    return {**kept, "PYTHONUNBUFFERED": "1"}  # an interpreter setting (log lines appear at once), not a service setting


def start(shell: ShellPort, host: Host, name: str, env: dict[str, str], env_file: Path) -> None:
    """Start the service. ``env`` only says which names the ``.env`` file defines; it is not passed on."""
    spec = host.services[name].spec
    service_dir = host.service_dir(name)
    python = shell.python_of(host.venv_dir(name))
    command = [python, service_dir / spec.entry]
    if not spec.dotenv:  # the service cannot read its .env: the runner does, then starts it
        command = [python, RUNNER, "--env-file", env_file, "--", service_dir / spec.entry]
    if shell.dry_run:
        shell.say(f"[dry-run] start {name}: {' '.join(map(str, command))}  (logs: {host.log_file(name)})")
        return
    if is_running(host, name):
        shell.say(f"{name}: already running (pid {read_pid(host, name)})")
        return
    host.log_file(name).parent.mkdir(parents=True, exist_ok=True)
    host.pid_file(name).parent.mkdir(parents=True, exist_ok=True)
    log = open(host.log_file(name), "ab")  # noqa: SIM115 - handed to the child process
    log.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n".encode())
    process_env = child_environment(env)
    if uses_console_window():
        # Own window per service, showing the same output that goes to the log file.
        log.close()
        wrapper = [
            sys.executable, TEE, "--name", name,
            "--log", host.log_file(name), "--pid-file", host.pid_file(name), "--", *command,
        ]
        process = subprocess.Popen(  # noqa: S603
            [str(part) for part in wrapper], cwd=service_dir, env=process_env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        host.pid_file(name).write_text(str(process.pid))
        shell.say(f"{name}: started in its own window (pid {process.pid})")
        return
    options: dict = {"start_new_session": True} if sys.platform != "win32" else {
        "creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    }
    process = subprocess.Popen(  # noqa: S603
        [str(part) for part in command], cwd=service_dir, env=process_env,
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **options,
    )
    host.pid_file(name).write_text(str(process.pid))
    shell.say(f"{name}: started (pid {process.pid})")


def stop(shell: ShellPort, host: Host, name: str) -> None:
    pid = read_pid(host, name)
    if shell.dry_run:
        shell.say(f"[dry-run] stop {name}")
        return
    if pid is None or not _pid_alive(pid):
        host.pid_file(name).unlink(missing_ok=True)
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
        while time.monotonic() < deadline and _pid_alive(pid):
            time.sleep(0.1)
        if _pid_alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
    host.pid_file(name).unlink(missing_ok=True)
    shell.say(f"{name}: stopped")
