"""Start the services of this machine at boot/login: a systemd user unit or a Windows scheduled task."""

from __future__ import annotations

import sys
from pathlib import Path

from application.ports.outbound.shell_port import ShellPort
from domain.entities.host import Host
from domain.errors import DeployError

ENTRY = Path(__file__).resolve().parents[3] / "main.py"


def _cli_command(host: Host, action: str) -> list[str]:
    # the config folder is named explicitly, so the boot start does not depend on the working directory
    return [sys.executable, str(ENTRY), action, "--host", host.name, "--config", str(host.config_dir)]


def systemd_unit(host: Host) -> str:
    start = " ".join(f'"{part}"' for part in _cli_command(host, "start"))
    stop = " ".join(f'"{part}"' for part in _cli_command(host, "stop"))
    return f"""[Unit]
Description=OBLIVION services on {host.name}
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart={start}
ExecStop={stop}

[Install]
WantedBy=default.target
"""


def unit_path(host: Host) -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"oblivion-{host.name}.service"


def task_name(host: Host) -> str:
    return f"OBLIVION-{host.name}"


def schtasks_command(host: Host) -> list[str]:
    run = " ".join(f'"{part}"' for part in _cli_command(host, "start"))
    # ONLOGON: the audio services need the logged-in user's session and sound devices
    return ["schtasks", "/Create", "/F", "/TN", task_name(host), "/SC", "ONLOGON", "/RL", "LIMITED", "/TR", run]


def install(shell: ShellPort, host: Host) -> None:
    if host.os_family == "windows":
        shell.run(schtasks_command(host))
        shell.say(f"scheduled task {task_name(host)} created (runs at logon)")
        return
    path = unit_path(host)
    if shell.dry_run:
        shell.say(f"[dry-run] write {path}:\n{systemd_unit(host)}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(systemd_unit(host), encoding="utf-8")
    shell.run(["systemctl", "--user", "daemon-reload"])
    shell.run(["systemctl", "--user", "enable", f"oblivion-{host.name}.service"])
    shell.say("For the services to start at boot without a login run once:  sudo loginctl enable-linger $USER")


def remove(shell: ShellPort, host: Host) -> None:
    if host.os_family == "windows":
        shell.run(["schtasks", "/Delete", "/F", "/TN", task_name(host)])
        return
    shell.run(["systemctl", "--user", "disable", "--now", f"oblivion-{host.name}.service"], check=False)
    if not shell.dry_run:
        unit_path(host).unlink(missing_ok=True)
    shell.run(["systemctl", "--user", "daemon-reload"], check=False)


def require_supported(host: Host) -> None:
    if host.os_family not in ("windows", "linux"):
        raise DeployError(f"autostart is not supported on {host.os_family}")
