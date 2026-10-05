"""``oblivion compat``: the services fit together on the code each will be deployed from."""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from application.services.compat_service import ERROR, OK, WARNING
from composition_root.container import new_compat_service
from infrastructure.config.paths import ConfigPaths
from infrastructure.config.settings_loader import resolved_refs
from infrastructure.inbound.cli import cli

ROOT = Path(__file__).resolve().parent.parent
BRANCH = "feature_ai_claude_2"
NAMES = ["tts", "stt"]


def git(cwd: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, env={**os.environ, **env}).stdout.strip()


def run_compat(catalogue, workspace: Path, *, remote: bool, names=None, refs=None):
    """The compat service on the real adapters; every service deployed from its catalogue branch unless ``refs`` says otherwise."""
    refs = refs or {name: (spec.branch, "config/catalogue.toml") for name, spec in catalogue.services.items()}
    return new_compat_service(catalogue).run(refs, workspace, remote=remote, names=names)


def make_service(workspace: Path, catalogue, name: str, *, version: str = "0.10.0", port: int | None = None, requirements_wheel: str | None = None) -> Path:
    """A service checkout on BRANCH with a bundled contracts wheel, requirements and .env.example."""
    spec = catalogue.services[name]
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


def make_workspace(tmp_path: Path, contracts: str = "0.10.0") -> Path:
    root = tmp_path / "ws"
    (root / "contracts").mkdir(parents=True)
    (root / "contracts" / "pyproject.toml").write_text(f'[project]\nname = "contracts-microservice"\nversion = "{contracts}"\n')
    return root


@pytest.fixture
def workspace(tmp_path, catalogue):
    root = make_workspace(tmp_path)
    for name in NAMES:
        make_service(root, catalogue, name)
    return root


def levels(findings, level):
    return [f for f in findings if f.level == level]


def test_services_on_the_same_contracts_version_are_compatible(catalogue, workspace):
    findings = run_compat(catalogue, workspace, remote=False, names=NAMES)
    assert not levels(findings, ERROR) and not levels(findings, WARNING)
    assert any(f.service == "contracts" and f.level == OK and "0.10.0" in f.message for f in findings)


def test_each_service_reports_which_file_its_ref_comes_from(catalogue, workspace, config):
    config.service("tts", 'tag = "v1.0.0"\n')
    findings = run_compat(catalogue, workspace, remote=False, names=NAMES, refs=resolved_refs(config.paths, catalogue))
    deployed = {f.service: f.message for f in findings if "deployed from" in f.message}
    assert "'v1.0.0'" in deployed["tts"] and "config/services/tts.toml (tag)" in deployed["tts"]
    assert "config/catalogue.toml" in deployed["stt"]


def test_different_contracts_versions_are_an_error(catalogue, tmp_path):
    root = make_workspace(tmp_path)
    make_service(root, catalogue, "tts", version="0.10.0")
    make_service(root, catalogue, "stt", version="0.9.0")
    errors = levels(run_compat(catalogue, root, remote=False, names=NAMES), ERROR)
    assert len(errors) == 1 and "different contracts versions" in errors[0].message and "stt=0.9.0" in errors[0].message


def test_a_bundle_older_than_the_contracts_source_is_an_error(catalogue, workspace):
    (workspace / "contracts" / "pyproject.toml").write_text('version = "0.11.0"\n')
    findings = run_compat(catalogue, workspace, remote=False, names=NAMES)
    assert any("source is 0.11.0" in f.message for f in levels(findings, ERROR))


def test_requirements_must_install_the_bundled_wheel(catalogue, tmp_path):
    root = make_workspace(tmp_path)
    make_service(root, catalogue, "tts", requirements_wheel="contracts_microservice-0.9.0-py3-none-any.whl")
    findings = run_compat(catalogue, root, remote=False, names=["tts"])
    assert any("does not install ./vendor/contracts_microservice-0.10.0" in f.message for f in levels(findings, ERROR))


def test_a_port_that_differs_from_the_catalogue_is_an_error(catalogue, tmp_path):
    root = make_workspace(tmp_path)
    make_service(root, catalogue, "tts", port=9999)
    findings = run_compat(catalogue, root, remote=False, names=["tts"])
    assert any("port 9999" in f.message and "catalogue" in f.message for f in levels(findings, ERROR))


def test_a_checkout_on_another_branch_than_the_deployed_one_is_a_warning(catalogue, workspace):
    git(workspace / "tts_microservice", "checkout", "-q", "-b", "scratch")
    findings = run_compat(catalogue, workspace, remote=False, names=["tts"])
    assert any("'scratch'" in f.message and BRANCH in f.message for f in levels(findings, WARNING))


def test_commits_that_are_not_pushed_are_a_warning(catalogue, workspace, tmp_path):
    folder = workspace / "tts_microservice"
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    git(folder, "remote", "add", "origin", str(bare))
    git(folder, "push", "-q", "-u", "origin", BRANCH)
    (folder / "new.txt").write_text("x")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "local only")
    findings = run_compat(catalogue, workspace, remote=False, names=["tts"])
    assert any("1 commit(s) not pushed" in f.message for f in levels(findings, WARNING))


def test_remote_check_finds_branches_and_tags_and_rejects_unknown_refs(catalogue, workspace, tmp_path):
    folder = workspace / "tts_microservice"
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    git(folder, "remote", "add", "origin", str(bare))
    git(folder, "tag", "v1.0.0")
    git(folder, "push", "-q", "origin", BRANCH, "v1.0.0")
    local = replace(catalogue, services={**catalogue.services, "tts": replace(catalogue.services["tts"], git=str(bare))})

    assert not levels(run_compat(local, workspace, remote=True, names=["tts"]), ERROR)

    tag = {"tts": ("v1.0.0", "config/services/tts.toml (tag)")}
    findings = run_compat(local, workspace, remote=True, names=["tts"], refs=tag)
    assert any("'v1.0.0' exists on the remote" in f.message for f in findings)

    missing = {"tts": ("v9.9.9", "config/services/tts.toml (tag)")}
    findings = run_compat(local, workspace, remote=True, names=["tts"], refs=missing)
    assert any("'v9.9.9' is not a branch or tag" in f.message for f in levels(findings, ERROR))


def test_a_remote_that_cannot_be_reached_is_an_error(catalogue, workspace, tmp_path):
    unreachable = replace(catalogue, services={**catalogue.services, "tts": replace(catalogue.services["tts"], git=str(tmp_path / "nowhere.git"))})
    findings = run_compat(unreachable, workspace, remote=True, names=["tts"])
    assert any("cannot reach" in f.message for f in levels(findings, ERROR))


def test_the_cli_exit_code_follows_the_errors(workspace, capsys):
    assert cli.main(["compat", "--workspace", str(workspace), "--service", "tts", "--service", "stt"]) in (0, 1)
    out = capsys.readouterr().out
    assert "deployed from" in out


def test_an_unknown_service_is_refused(capsys):
    assert cli.main(["compat", "--service", "nope"]) == 2
    assert "unknown service" in capsys.readouterr().err


def test_the_real_workspace_is_compatible(catalogue):
    if not all((ROOT.parent / n).exists() for n in ("contracts", "brain_microservice", "stepper_microservice")):
        pytest.skip("no workspace next to this repository")
    findings = run_compat(catalogue, ROOT.parent, remote=False, refs=resolved_refs(ConfigPaths(), catalogue))
    assert not levels(findings, ERROR), [f.message for f in levels(findings, ERROR)]
