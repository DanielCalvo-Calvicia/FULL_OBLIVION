"""Linux/Raspberry Pi system packages on a machine that was just installed."""

from __future__ import annotations

from pathlib import Path

from infrastructure.outbound.installer.native_installer import NativeInstaller
from infrastructure.outbound.shell.shell import Shell


def _dry_install(config, tmp_path: Path, capsys, *services: str) -> list[str]:
    config.layout({"robot": list(services)}).machine("robot", os="linux", workdir=tmp_path / "work")
    host = config.host("robot")
    installer = NativeInstaller(Shell(dry_run=True))
    for name in services:
        installer.install_native(host, config.catalogue, name, previous_fingerprint=None, system_deps=True)
    return [line for line in capsys.readouterr().out.splitlines() if "apt-get" in line]


def test_package_lists_are_refreshed_once_before_the_first_install(config, tmp_path, capsys):
    """A fresh Debian/Pi image has empty package lists: `apt-get install` alone fails with 'Unable to locate'."""
    commands = _dry_install(config, tmp_path, capsys, "speaker", "tts")
    assert len(commands) == 3
    assert commands[0].endswith("sudo apt-get update")
    assert all("apt-get install -y" in line for line in commands[1:])


def test_the_speaker_gets_the_audio_file_library_a_32_bit_pi_lacks(config, tmp_path, capsys):
    (install,) = [line for line in _dry_install(config, tmp_path, capsys, "speaker") if "install" in line]
    assert "libsndfile1" in install and "libportaudio2" in install
