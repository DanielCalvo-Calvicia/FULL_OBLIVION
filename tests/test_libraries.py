"""Shared libraries and the fresh-machine path: what a machine gets when only this repository was cloned."""

from __future__ import annotations

import shutil
import tomllib
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import ALL_SERVICES, Config

from composition_root.container import new_deployment_service
from domain.entities.catalogue import Catalogue
from domain.errors import DeployError
from domain.rules.host_validation import validate_host
from infrastructure.config.paths import ConfigPaths
from infrastructure.outbound.installer import native_installer as installer
from infrastructure.outbound.shell.shell import Shell

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BRANCH = "feature_ai_claude_2"  # the branch that carries the vendored contracts wheel every service needs


def catalogue_with(base: Path, **library: str) -> Catalogue:
    return Catalogue(services={}, libraries={"shared-logging": library}, base_dir=base)


def make_wheel(folder: Path, version: str = "0.1.0") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    wheel = folder / f"shared_logging-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("shared_logging/__init__.py", "")
    return wheel


def make_checkout(path: Path, version: str = "0.1.0") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "pyproject.toml").write_text(f'[project]\nname = "shared-logging"\nversion = "{version}"\n')
    (path / "shared_logging").mkdir(exist_ok=True)
    (path / "shared_logging" / "__init__.py").write_text("")
    return path


# --------------------------------------------------------------------------- source selection


def test_the_workspace_checkout_wins_when_it_exists(tmp_path):
    make_checkout(tmp_path / "shared-logging")
    make_wheel(tmp_path / "wheels")
    catalogue = catalogue_with(tmp_path, path="shared-logging", wheel_dir="wheels")
    assert installer.library_source(catalogue, "shared-logging") == ("path", (tmp_path / "shared-logging").resolve())


def test_a_machine_without_the_workspace_uses_the_bundled_wheel(tmp_path):
    make_wheel(tmp_path / "wheels")
    catalogue = catalogue_with(tmp_path, path="missing-checkout", wheel_dir="wheels")
    kind, location = installer.library_source(catalogue, "shared-logging")
    assert (kind, Path(location)) == ("wheel_dir", (tmp_path / "wheels").resolve())


def test_a_relative_wheel_dir_is_relative_to_the_repository_root_not_to_the_current_directory(tmp_path, monkeypatch):
    make_wheel(tmp_path / "wheels")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # pip runs inside the service folder, so cwd is never the repository root
    args = installer.library_pip_args(catalogue_with(tmp_path, wheel_dir="wheels"), "shared-logging")
    assert str((tmp_path / "wheels").resolve()) in args


def test_the_wheel_is_installed_from_disk_only_and_always_replaces_the_installed_copy(tmp_path):
    make_wheel(tmp_path / "wheels")
    args = installer.library_pip_args(catalogue_with(tmp_path, wheel_dir="wheels"), "shared-logging")
    assert "--no-index" in args  # a same-named package on PyPI must never win
    assert "--force-reinstall" in args  # a rebuilt wheel with the same version still takes effect
    assert args[-1] == "shared-logging"


def test_git_is_the_last_resort(tmp_path):
    catalogue = catalogue_with(tmp_path, path="nope", wheel_dir="no-wheels", git="https://example.invalid/x.git@main")
    assert installer.library_pip_args(catalogue, "shared-logging") == ["git+https://example.invalid/x.git@main"]


def test_no_usable_source_says_where_it_looked_and_how_to_fix_it(tmp_path):
    (tmp_path / "wheels").mkdir()  # exists, but holds no shared-logging wheel
    catalogue = catalogue_with(tmp_path, path="nope", wheel_dir="wheels")
    with pytest.raises(DeployError) as raised:
        installer.library_source(catalogue, "shared-logging")
    message = str(raised.value)
    assert "nope" in message and "no shared-logging wheel" in message and "bundle_shared_logging.py" in message


def test_changing_the_bundled_wheel_changes_the_install_fingerprint(tmp_path):
    wheel = make_wheel(tmp_path / "wheels")
    catalogue = catalogue_with(tmp_path, wheel_dir="wheels")
    before = installer._library_stamp(catalogue, "shared-logging")
    wheel.write_bytes(wheel.read_bytes() + b"x")  # same name, different content
    assert installer._library_stamp(catalogue, "shared-logging") != before


def test_an_outdated_bundled_wheel_is_reported_where_a_checkout_exists(tmp_path):
    make_checkout(tmp_path / "shared-logging", version="0.2.0")
    make_wheel(tmp_path / "wheels", version="0.1.0")
    catalogue = catalogue_with(tmp_path, path="shared-logging", wheel_dir="wheels")
    errors, warnings = installer.check_libraries(catalogue, {"shared-logging"})
    assert errors == []
    assert len(warnings) == 1 and "0.2.0" in warnings[0] and "0.1.0" in warnings[0]
    make_wheel(tmp_path / "wheels", version="0.2.0")
    assert installer.check_libraries(catalogue, {"shared-logging"}) == ([], [])


# --------------------------------------------------------------------------- the shipped repository


def test_the_shipped_wheel_matches_the_workspace_checkout_it_was_built_from(catalogue):
    (wheel,) = (ROOT / "wheels").glob("shared_logging-*.whl")
    checkout = (catalogue.base_dir / catalogue.libraries["shared-logging"]["path"]).resolve()
    if not (checkout / "pyproject.toml").exists():
        pytest.skip("no workspace next to this repository")
    with (checkout / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    assert wheel.name.split("-")[1] == version, "run scripts/bundle_shared_logging.py and commit the wheel"
    with zipfile.ZipFile(wheel) as archive:
        packaged = {n for n in archive.namelist() if n.startswith("shared_logging/") and n.endswith(".py")}
    on_disk = {
        f"shared_logging/{p.relative_to(checkout / 'shared_logging').as_posix()}"
        for p in (checkout / "shared_logging").rglob("*.py")
        if "__pycache__" not in p.parts
    }
    assert packaged == on_disk


def test_a_fresh_machine_without_the_workspace_can_deploy_every_service_of_every_shipped_layout(catalogue, tmp_path):
    """Only this repository was cloned: nothing named ../shared-logging exists next to it."""
    fresh = replace(catalogue, libraries={"shared-logging": {**catalogue.libraries["shared-logging"], "path": str(tmp_path / "absent")}})
    kind, _ = installer.library_source(fresh, "shared-logging")
    assert kind == "wheel_dir"
    layouts = sorted(ConfigPaths().layouts.glob("*.toml"))
    assert layouts, "no layouts shipped"
    for layout in layouts:
        config = Config(tmp_path / layout.stem, fresh)
        config.paths.layouts.mkdir(parents=True)
        shutil.copy(layout, config.paths.layouts / layout.name)
        addresses = {line.split("]")[0].split(".", 1)[1]: "192.168.1.50" for line in layout.read_text().splitlines() if line.startswith("[machines.")}
        config.paths.robot.write_text(f'layout = "{layout.stem}"\n[addresses]\n' + "".join(f'{m} = "{a}"\n' for m, a in addresses.items()))
        for machine in addresses:
            host = config.host(machine)
            errors, _ = new_deployment_service(host, fresh, shell=Shell(dry_run=True)).validate(None)
            assert not [e for e in errors if "shared-logging" in e], f"{layout.name}/{machine}: {errors}"


def test_an_unusable_library_stops_the_deploy_before_anything_is_cloned(catalogue, config, tmp_path):
    broken = replace(catalogue, libraries={"shared-logging": {"path": str(tmp_path / "absent")}})
    config.layout({"robot": ALL_SERVICES})
    host = replace(config.host("robot"), workdir=tmp_path / "work")
    with pytest.raises(DeployError, match="shared-logging"):
        new_deployment_service(host, broken, shell=Shell(dry_run=True)).deploy(None)
    assert not (tmp_path / "work").exists()


def test_every_service_defaults_to_the_branch_that_carries_the_vendored_contracts_wheel(catalogue):
    assert {spec.branch for spec in catalogue.services.values()} == {DEFAULT_BRANCH}


# --------------------------------------------------------------------------- addresses of the other machines


def test_a_malformed_address_is_refused_when_the_layout_loads(config):
    for bad in ("ftp://192.168.1.20", "the speaker box", "192.168.1.20:8000", "192.168.1.20/path"):
        config.layout({"m": ["brain"], "other": ["microphone"]}, addresses={"m": "127.0.0.1", "other": bad})
        with pytest.raises(DeployError, match="must be an IP or a host name"):
            config.host("m")


def test_a_loopback_address_for_another_machine_is_a_warning(config):
    config.layout(
        {"m": ["brain"], "other": ["microphone", "stt", "tts", "speaker", "ai-agent"]},
        addresses={"m": "192.168.1.10", "other": "127.0.0.1"},
    )
    errors, warnings = validate_host(config.host("m"))
    assert errors == []
    assert any("microphone" in w and "this machine" in w for w in warnings)
