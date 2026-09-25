"""Tracked __pycache__ files rewritten by running a service are not 'local modifications'."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from oblivion import gitops
from oblivion.config import DeployError
from oblivion.shell import Shell


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
    _git(remote, "add", "-A")
    _git(remote, "commit", "-qm", "init")
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True)
    return repo, remote


def test_rewritten_bytecode_is_restored_and_does_not_block_sync(clone):
    repo, remote = clone
    (repo / "__pycache__" / "a.cpython-314.pyc").write_bytes(b"rewritten by python")
    previous, new = gitops.sync(Shell(), str(remote), repo, "main")
    assert previous == new
    assert (repo / "__pycache__" / "a.cpython-314.pyc").read_bytes() == b"old"


def test_a_real_edit_next_to_bytecode_is_still_refused(clone):
    repo, remote = clone
    (repo / "__pycache__" / "a.cpython-314.pyc").write_bytes(b"rewritten by python")
    (repo / "main.py").write_text("x = 2\n")
    with pytest.raises(DeployError, match="local modifications"):
        gitops.sync(Shell(), str(remote), repo, "main")
    assert (repo / "main.py").read_text() == "x = 2\n"
