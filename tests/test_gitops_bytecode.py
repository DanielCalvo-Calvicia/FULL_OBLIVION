"""Tracked __pycache__ files and the generated .env that deploying rewrites are not 'local modifications'."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from infrastructure.outbound.git.git_source_control import GitSourceControl
from domain.errors import DeployError
from infrastructure.outbound.env.dotenv_files import GENERATED_HEADER
from infrastructure.outbound.shell.shell import Shell


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True
    )


@pytest.fixture
def clone(tmp_path):
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "-q", "-b", "main")
    (remote / "__pycache__").mkdir()
    (remote / "__pycache__" / "a.cpython-314.pyc").write_bytes(b"old")
    (remote / "main.py").write_text("x = 1\n")
    (remote / ".env").write_text("SERVICE_PORT=8005\n")  # the stepper repo tracks its .env
    _git(remote, "add", "-A")
    _git(remote, "commit", "-qm", "init")
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True)
    return repo, remote


def test_rewritten_bytecode_is_restored_and_does_not_block_sync(clone):
    repo, remote = clone
    (repo / "__pycache__" / "a.cpython-314.pyc").write_bytes(b"rewritten by python")
    previous, new = GitSourceControl(Shell()).sync(str(remote), repo, "main")
    assert previous == new
    assert (repo / "__pycache__" / "a.cpython-314.pyc").read_bytes() == b"old"


def test_a_real_edit_next_to_bytecode_is_still_refused(clone):
    repo, remote = clone
    (repo / "__pycache__" / "a.cpython-314.pyc").write_bytes(b"rewritten by python")
    (repo / "main.py").write_text("x = 2\n")
    with pytest.raises(DeployError, match="local modifications"):
        GitSourceControl(Shell()).sync(str(remote), repo, "main")
    assert (repo / "main.py").read_text() == "x = 2\n"


def test_the_env_file_this_tool_generated_does_not_block_the_next_update(clone):
    repo, remote = clone
    (repo / ".env").write_text(GENERATED_HEADER.format(machine="pi") + "SERVICE_PORT=8005\nMOCK_HARDWARE=0\n")
    previous, new = GitSourceControl(Shell()).sync(str(remote), repo, "main")
    assert previous == new
    assert (repo / ".env").read_text() == "SERVICE_PORT=8005\n"  # back to the committed file; deploy rewrites it next


def test_a_hand_edited_tracked_env_is_still_refused(clone):
    repo, remote = clone
    (repo / ".env").write_text("SERVICE_PORT=9999\n")
    with pytest.raises(DeployError, match="local modifications"):
        GitSourceControl(Shell()).sync(str(remote), repo, "main")
    assert (repo / ".env").read_text() == "SERVICE_PORT=9999\n"


def test_a_dry_run_does_not_report_rewritten_bytecode_or_a_generated_env_as_local_edits(clone):
    """A dry run restores nothing, so the dirty check itself must ignore what a real run would restore."""
    repo, remote = clone
    (repo / "__pycache__" / "a.cpython-314.pyc").write_bytes(b"rewritten by python")
    (repo / ".env").write_text(GENERATED_HEADER.format(machine="pc") + "SERVICE_PORT=8005\n")
    GitSourceControl(Shell(dry_run=True, echo=False)).sync(str(remote), repo, "main")  # no DeployError
    assert (repo / "__pycache__" / "a.cpython-314.pyc").read_bytes() == b"rewritten by python"  # and nothing was touched


def test_a_dry_run_still_refuses_a_real_edit(clone):
    repo, remote = clone
    (repo / "main.py").write_text("x = 2\n")
    with pytest.raises(DeployError, match="local modifications"):
        GitSourceControl(Shell(dry_run=True, echo=False)).sync(str(remote), repo, "main")
