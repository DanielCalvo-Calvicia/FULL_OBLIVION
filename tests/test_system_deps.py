"""Linux/Raspberry Pi system packages on a machine that was just installed."""

from __future__ import annotations

import textwrap
from pathlib import Path

from oblivion import installer
from oblivion.config import load_host, load_registry
from oblivion.shell import Shell

ROOT = Path(__file__).resolve().parent.parent


def _dry_install(tmp_path: Path, capsys, *services: str) -> list[str]:
    registry = load_registry(ROOT / "services.toml")
    path = tmp_path / "h.toml"
    path.write_text(textwrap.dedent(f"""
        [host]
        os = "linux"
        workdir = "{(tmp_path / 'work').as_posix()}"
    """) + "".join(f"[services.{name}]\n" for name in services))
    host = load_host(str(path), registry)
    shell = Shell(dry_run=True)
    for name in services:
        installer.install_native(shell, host, registry, name, previous_fingerprint=None, system_deps=True)
    return [line for line in capsys.readouterr().out.splitlines() if "apt-get" in line]


def test_package_lists_are_refreshed_once_before_the_first_install(tmp_path, capsys):
    """A fresh Debian/Pi image has empty package lists: `apt-get install` alone fails with 'Unable to locate'."""
    commands = _dry_install(tmp_path, capsys, "speaker", "tts")
    assert len(commands) == 3
    assert commands[0].endswith("sudo apt-get update")
    assert all("apt-get install -y" in line for line in commands[1:])


def test_the_speaker_gets_the_audio_file_library_a_32_bit_pi_lacks(tmp_path, capsys):
    (install,) = [line for line in _dry_install(tmp_path, capsys, "speaker") if "install" in line]
    assert "libsndfile1" in install and "libportaudio2" in install
