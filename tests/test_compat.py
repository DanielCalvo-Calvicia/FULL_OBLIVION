"""``oblivion compat``: the services fit together on the code each will be deployed from."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from oblivion import cli
from oblivion.compat import ERROR, OK, WARNING, run_compat
from oblivion.config import load_registry
from oblivion.shell import Shell

ROOT = Path(__file__).resolve().parent.parent
BRANCH = "feature_ai_claude_2"
NAMES = ["tts", "stt"]


def git(cwd: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    import os

    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, env={**os.environ, **env}).stdout.strip()


def make_service(workspace: Path, registry, name: str, *, version: str = "0.10.0", port: int | None = None, requirements_wheel: str | None = None) -> Path:
    """A service checkout on BRANCH with a bundled contracts wheel, requirements and .env.example."""
    spec = registry.services[name]
    folder = workspace / spec.repo_dir
    (folder / "vendor").mkdir(parents=True)
    wheel = f"contracts_microservice-{version}-py3-none-any.whl"
    (folder / "vendor" / wheel).write_bytes(b"wheel")
    for relative in spec.requirements.values():
        (folder / relative).write_text(f"fastapi\n./vendor/{requirements_wheel or wheel}\n")
    (folder / ".env.example").write_text(f"SERVICE_PORT={port or spec.port}\n")
    git(folder, "init", "-q", "-b", BRANCH)
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "init")
    return folder


@pytest.fixture
def registry(tmp_path):
    base = tmp_path / "deployment"
    base.mkdir()
    return replace(load_registry(ROOT / "services.toml"), base_dir=base)


@pytest.fixture
def workspace(tmp_path, registry):
    root = tmp_path / "workspace"
    (root / "contracts").mkdir(parents=True)
    (root / "contracts" / "pyproject.toml").write_text('[project]\nname = "contracts-microservice"\nversion = "0.10.0"\n')
    for name in NAMES:
        make_service(root, registry, name)
    return root


def levels(findings, level):
    return [f for f in findings if f.level == level]


def test_services_on_the_same_contracts_version_are_compatible(registry, workspace):
    findings = run_compat(registry, Shell(echo=False), workspace, remote=False, names=NAMES)
    assert not levels(findings, ERROR) and not levels(findings, WARNING)
    assert any(f.service == "contracts" and f.level == OK and "0.10.0" in f.message for f in findings)


def test_each_service_reports_where_its_ref_comes_from(registry, workspace):
    (registry.base_dir / "services").mkdir()
    (registry.base_dir / "services" / "tts.toml").write_text('tag = "v1.0.0"\n')
    findings = run_compat(registry, Shell(echo=False), workspace, remote=False, names=NAMES)
    deployed = {f.service: f.message for f in findings if "deployed from" in f.message}
    assert "'v1.0.0'" in deployed["tts"] and "services/tts.toml (tag)" in deployed["tts"]
    assert "services.toml" in deployed["stt"]


def test_different_contracts_versions_are_an_error(registry, tmp_path):
    root = tmp_path / "ws"
    (root / "contracts").mkdir(parents=True)
    (root / "contracts" / "pyproject.toml").write_text('version = "0.10.0"\n')
    make_service(root, registry, "tts", version="0.10.0")
    make_service(root, registry, "stt", version="0.9.0")
    findings = run_compat(registry, Shell(echo=False), root, remote=False, names=NAMES)
    errors = levels(findings, ERROR)
    assert len(errors) == 1 and "different contracts versions" in errors[0].message and "stt=0.9.0" in errors[0].message


def test_a_bundle_older_than_the_contracts_source_is_an_error(registry, workspace):
    (workspace / "contracts" / "pyproject.toml").write_text('version = "0.11.0"\n')
    findings = run_compat(registry, Shell(echo=False), workspace, remote=False, names=NAMES)
    assert any("source is 0.11.0" in f.message for f in levels(findings, ERROR))


def test_requirements_must_install_the_bundled_wheel(registry, tmp_path):
    root = tmp_path / "ws"
    (root / "contracts").mkdir(parents=True)
    (root / "contracts" / "pyproject.toml").write_text('version = "0.10.0"\n')
    make_service(root, registry, "tts", requirements_wheel="contracts_microservice-0.9.0-py3-none-any.whl")
    findings = run_compat(registry, Shell(echo=False), root, remote=False, names=["tts"])
    assert any("does not install ./vendor/contracts_microservice-0.10.0" in f.message for f in levels(findings, ERROR))


def test_a_port_that_differs_from_the_catalogue_is_an_error(registry, tmp_path):
    root = tmp_path / "ws"
    (root / "contracts").mkdir(parents=True)
    (root / "contracts" / "pyproject.toml").write_text('version = "0.10.0"\n')
    make_service(root, registry, "tts", port=9999)
    findings = run_compat(registry, Shell(echo=False), root, remote=False, names=["tts"])
    assert any("port 9999" in f.message for f in levels(findings, ERROR))


def test_a_checkout_on_another_branch_than_the_deployed_one_is_a_warning(registry, workspace):
    git(workspace / "tts_microservice", "checkout", "-q", "-b", "scratch")
    findings = run_compat(registry, Shell(echo=False), workspace, remote=False, names=["tts"])
    assert any("'scratch'" in f.message and BRANCH in f.message for f in levels(findings, WARNING))


def test_commits_that_are_not_pushed_are_a_warning(registry, workspace, tmp_path):
    folder = workspace / "tts_microservice"
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    git(folder, "remote", "add", "origin", str(bare))
    git(folder, "push", "-q", "-u", "origin", BRANCH)
    (folder / "new.txt").write_text("x")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "local only")
    findings = run_compat(registry, Shell(echo=False), workspace, remote=False, names=["tts"])
    assert any("1 commit(s) not pushed" in f.message for f in levels(findings, WARNING))


def test_remote_check_finds_branches_and_tags_and_rejects_unknown_refs(registry, workspace, tmp_path):
    folder = workspace / "tts_microservice"
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    git(folder, "remote", "add", "origin", str(bare))
    git(folder, "tag", "v1.0.0")
    git(folder, "push", "-q", "origin", BRANCH, "v1.0.0")
    local = replace(registry, services={**registry.services, "tts": replace(registry.services["tts"], git=str(bare))})

    assert not levels(run_compat(local, Shell(echo=False), workspace, remote=True, names=["tts"]), ERROR)

    (local.base_dir / "services").mkdir()
    (local.base_dir / "services" / "tts.toml").write_text('tag = "v1.0.0"\n')
    findings = run_compat(local, Shell(echo=False), workspace, remote=True, names=["tts"])
    assert any("'v1.0.0' exists on the remote" in f.message for f in findings)

    (local.base_dir / "services" / "tts.toml").write_text('tag = "v9.9.9"\n')
    findings = run_compat(local, Shell(echo=False), workspace, remote=True, names=["tts"])
    assert any("'v9.9.9' is not a branch or tag" in f.message for f in levels(findings, ERROR))


def test_the_cli_exit_code_follows_the_errors(registry, workspace, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", ROOT)
    assert cli.main(["compat", "--workspace", str(workspace), "--service", "tts", "--service", "stt"]) in (0, 1)
    out = capsys.readouterr().out
    assert "deployed from" in out


def test_an_unknown_service_is_refused(capsys):
    assert cli.main(["compat", "--service", "nope"]) == 2
    assert "unknown service" in capsys.readouterr().err


def test_the_real_workspace_is_compatible():
    if not all((ROOT.parent / n).exists() for n in ("contracts", "brain_microservice", "stepper_microservice")):
        pytest.skip("no workspace next to this repository")
    findings = run_compat(load_registry(ROOT / "services.toml"), Shell(echo=False), ROOT.parent, remote=False)
    assert not levels(findings, ERROR), [f.message for f in levels(findings, ERROR)]
