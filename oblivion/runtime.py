"""Starting, stopping and inspecting a service, natively or in a Docker container."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from .config import DeployError, Host
from .shell import Shell

STOP_TIMEOUT_SECONDS = 10.0
CONTAINER_ENV_FILE = "/app/.env"  # the Dockerfile's WORKDIR is /app


def container_name(name: str) -> str:
    return f"oblivion-{name}"


def image_name(name: str) -> str:
    return f"oblivion/{name}:local"


# --------------------------------------------------------------------------- native


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


def native_running(host: Host, name: str) -> bool:
    pid = read_pid(host, name)
    return pid is not None and _pid_alive(pid)


def uses_console_window() -> bool:
    """Windows shows each service in its own console window. Set OBLIVION_CONSOLE=0 for headless (tests, CI)."""
    return sys.platform == "win32" and os.environ.get("OBLIVION_CONSOLE", "1") != "0"


RUNNER = Path(__file__).with_name("service_runner.py")


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


def native_start(shell: Shell, host: Host, name: str, env: dict[str, str], env_file: Path) -> None:
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
    if native_running(host, name):
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
            sys.executable, Path(__file__).with_name("tee.py"), "--name", name,
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


def native_stop(shell: Shell, host: Host, name: str) -> None:
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


# --------------------------------------------------------------------------- docker


def docker_build(shell: Shell, host: Host, name: str, context: Path) -> None:
    spec = host.services[name].spec
    dockerfile = Path(__file__).resolve().parent.parent / "docker" / "service.Dockerfile"
    args = ["docker", "build", "-t", image_name(name), "-f", dockerfile, context]
    if spec.apt:
        args[2:2] = ["--build-arg", f"APT_PACKAGES={' '.join(spec.apt)}"]
    if spec.prepare:  # runs while building, with the service's default settings (no .env exists yet)
        args[2:2] = ["--build-arg", f"PREPARE={' '.join(spec.prepare)}"]
    shell.run(args)


def docker_start(shell: Shell, host: Host, name: str, env_file: Path) -> None:
    instance = host.services[name]
    shell.run(["docker", "rm", "-f", container_name(name)], check=False, capture=True)
    command = [
        "docker", "run", "-d", "--name", container_name(name), "--restart", "unless-stopped",
        "-p", f"{host.bind}:{instance.port}:{instance.port}",
        "--add-host", "host.docker.internal:host-gateway",
    ]
    if instance.spec.dotenv:
        # The file itself, read-only, where the service's own dotenv loading finds it: no variables in the container.
        command += ["--mount", f"type=bind,source={env_file},target={CONTAINER_ENV_FILE},readonly"]
    else:
        command += ["--env-file", env_file]  # a service that cannot read a .env: the only way to hand it its settings
    if instance.spec.audio and host.os_family == "linux":
        command += ["--device", "/dev/snd"]
    shell.run([*command, image_name(name)])


def docker_stop(shell: Shell, host: Host, name: str) -> None:
    shell.run(["docker", "rm", "-f", container_name(name)], check=False, capture=True)
    shell.say(f"{name}: container removed")


def docker_running(shell: Shell, name: str) -> bool:
    result = shell.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name(name)], check=False, capture=True, mutating=False
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def prepare_docker_context(shell: Shell, host: Host, name: str, requirements_text: str, library_wheels: list[Path]) -> Path:
    """A build folder: the service tree (without .git), filtered requirements and shared-library wheels."""
    context = host.workdir / "build" / name
    if shell.dry_run:
        return context
    if context.exists():
        shutil.rmtree(context)
    shutil.copytree(
        host.service_dir(name), context,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv", "windows", ".env", "*.pyc"),
    )
    (context / "requirements.docker.txt").write_text(requirements_text, encoding="utf-8")
    libs = context / "libs"
    libs.mkdir(exist_ok=True)
    for wheel in library_wheels:
        shutil.copy2(wheel, libs / wheel.name)
    (libs / ".keep").write_text("")
    return context


# --------------------------------------------------------------------------- dispatch


def is_running(shell: Shell, host: Host, name: str) -> bool:
    if host.services[name].runtime == "docker":
        return docker_running(shell, name)
    return native_running(host, name)


def require_docker(shell: Shell) -> None:
    if shutil.which("docker") is None:
        raise DeployError("docker is not installed or not on PATH (needed for runtime = \"docker\")")
