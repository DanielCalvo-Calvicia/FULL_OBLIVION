"""Running a service in a Docker container: build the image, start, stop, ask."""

from __future__ import annotations

import shutil
from pathlib import Path

from application.ports.outbound.shell_port import ShellPort
from domain.entities.host import Host
from domain.errors import DeployError

CONTAINER_ENV_FILE = "/app/.env"  # the Dockerfile's WORKDIR is /app
DOCKERFILE = Path(__file__).resolve().parents[3] / "docker" / "service.Dockerfile"


def container_name(name: str) -> str:
    return f"oblivion-{name}"


def image_name(name: str) -> str:
    return f"oblivion/{name}:local"


def require_docker() -> None:
    if shutil.which("docker") is None:
        raise DeployError("docker is not installed or not on PATH (needed for runtime = \"docker\")")


def build(shell: ShellPort, host: Host, name: str, context: Path) -> None:
    spec = host.services[name].spec
    args = ["docker", "build", "-t", image_name(name), "-f", DOCKERFILE, context]
    if spec.apt:
        args[2:2] = ["--build-arg", f"APT_PACKAGES={' '.join(spec.apt)}"]
    if spec.prepare:  # runs while building, with the service's default settings (no .env exists yet)
        args[2:2] = ["--build-arg", f"PREPARE={' '.join(spec.prepare)}"]
    shell.run(args)


def start(shell: ShellPort, host: Host, name: str, env_file: Path) -> None:
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


def stop(shell: ShellPort, host: Host, name: str) -> None:
    shell.run(["docker", "rm", "-f", container_name(name)], check=False, capture=True)
    shell.say(f"{name}: container removed")


def is_running(shell: ShellPort, name: str) -> bool:
    result = shell.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name(name)], check=False, capture=True, mutating=False
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def prepare_context(shell: ShellPort, host: Host, name: str, requirements_text: str, library_wheels: list[Path]) -> Path:
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
