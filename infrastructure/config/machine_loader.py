"""``config/machines/<name>.toml``: what is particular to one physical machine (its Python, its folders, its OS).

Optional. Without a file the machine uses the defaults::

    [host]
    python = "/home/pi/.local/bin/python3.12"   # when the default python3 is older than a service needs (ai-agent: 3.12)
    workdir = "~/oblivion"                      # clones, virtualenvs, logs and state
    os = "raspberry"                            # auto (default), windows, linux or raspberry: only to force it
    bind = "127.0.0.1"                          # only to override the address the services listen on
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

from domain.errors import DeployError
from infrastructure.config.paths import ConfigPaths
from infrastructure.config.toml_reader import check_keys, read_toml

OS_CHOICES = ("auto", "windows", "linux", "raspberry")


@dataclass(frozen=True)
class MachineSettings:
    os: str = "auto"
    workdir: str | None = None
    python: str | None = None
    bind: str | None = None


def load_machine_settings(paths: ConfigPaths, machine: str) -> MachineSettings:
    path = paths.machine_file(machine)
    if not path.exists():
        return MachineSettings()
    data = read_toml(path)
    check_keys(path, data, {"host"}, "allowed: a [host] table")
    section = data.get("host", {})
    check_keys(path, section, {"os", "workdir", "python", "bind"}, "allowed under [host]: os, workdir, python, bind")
    declared = section.get("os", "auto")
    if declared not in OS_CHOICES:
        raise DeployError(f"{path}: os must be one of {', '.join(OS_CHOICES)}")
    return MachineSettings(
        os=declared,
        workdir=str(section["workdir"]) if "workdir" in section else None,
        python=str(section["python"]) if section.get("python") else None,
        bind=str(section["bind"]) if "bind" in section else None,
    )


def detect_os() -> tuple[str, bool]:
    """``(os family, is a Raspberry Pi)``."""
    system = platform.system().lower()
    if system == "windows":
        return "windows", False
    # The board says so itself. The CPU architecture alone proves nothing: an ARM server is not a Raspberry Pi
    # (it has no GPIO), and a wrong guess picks the wrong requirements file.
    for source in ("/proc/device-tree/model", "/proc/cpuinfo"):
        try:
            if "raspberry pi" in Path(source).read_text(errors="ignore").lower():
                return "linux", True
        except OSError:
            continue
    return "linux", False
