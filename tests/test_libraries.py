"""Shared libraries and the fresh-machine path: what a machine gets when only this repository was cloned."""

from __future__ import annotations

import sys
import textwrap
import tomllib
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import launch  # noqa: E402
from oblivion import installer  # noqa: E402
from oblivion.config import DeployError, Registry, load_host, load_registry, validate_host  # noqa: E402
from oblivion.manager import Manager  # noqa: E402
from oblivion.shell import Shell  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def registry_with(base: Path, **library: str) -> Registry:
    return Registry(services={}, libraries={"shared-logging": library}, base_dir=base)


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
    registry = registry_with(tmp_path, path="shared-logging", wheel_dir="wheels")
    assert installer.library_source(registry, "shared-logging") == ("path", (tmp_path / "shared-logging").resolve())


def test_a_machine_without_the_workspace_uses_the_bundled_wheel(tmp_path):
    make_wheel(tmp_path / "wheels")
    registry = registry_with(tmp_path, path="missing-checkout", wheel_dir="wheels")
    kind, location = installer.library_source(registry, "shared-logging")
    assert (kind, Path(location)) == ("wheel_dir", (tmp_path / "wheels").resolve())


def test_a_relative_wheel_dir_is_relative_to_services_toml_not_to_the_current_directory(tmp_path, monkeypatch):
    make_wheel(tmp_path / "wheels")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # pip runs inside the service folder, so cwd is never the registry folder
    args = installer.library_pip_args(registry_with(tmp_path, wheel_dir="wheels"), "shared-logging")
    assert str((tmp_path / "wheels").resolve()) in args


def test_the_wheel_is_installed_from_disk_only_and_always_replaces_the_installed_copy(tmp_path):
    make_wheel(tmp_path / "wheels")
    args = installer.library_pip_args(registry_with(tmp_path, wheel_dir="wheels"), "shared-logging")
    assert "--no-index" in args  # a same-named package on PyPI must never win
    assert "--force-reinstall" in args  # a rebuilt wheel with the same version still takes effect
    assert args[-1] == "shared-logging"


def test_git_is_the_last_resort(tmp_path):
    registry = registry_with(tmp_path, path="nope", wheel_dir="no-wheels", git="https://example.invalid/x.git@main")
    assert installer.library_pip_args(registry, "shared-logging") == ["git+https://example.invalid/x.git@main"]


def test_no_usable_source_says_where_it_looked_and_how_to_fix_it(tmp_path):
    (tmp_path / "wheels").mkdir()  # exists, but holds no shared-logging wheel
    registry = registry_with(tmp_path, path="nope", wheel_dir="wheels")
    with pytest.raises(DeployError) as raised:
        installer.library_source(registry, "shared-logging")
    message = str(raised.value)
    assert "nope" in message and "no shared-logging wheel" in message and "bundle_shared_logging.py" in message


def test_changing_the_bundled_wheel_changes_the_install_fingerprint(tmp_path):
    wheel = make_wheel(tmp_path / "wheels")
    registry = registry_with(tmp_path, wheel_dir="wheels")
    before = installer._library_stamp(registry, "shared-logging")
    wheel.write_bytes(wheel.read_bytes() + b"x")  # same name, different content
    assert installer._library_stamp(registry, "shared-logging") != before


def test_an_outdated_bundled_wheel_is_reported_where_a_checkout_exists(tmp_path):
    make_checkout(tmp_path / "shared-logging", version="0.2.0")
    make_wheel(tmp_path / "wheels", version="0.1.0")
    registry = registry_with(tmp_path, path="shared-logging", wheel_dir="wheels")
    errors, warnings = installer.check_libraries(registry, {"shared-logging"})
    assert errors == []
    assert len(warnings) == 1 and "0.2.0" in warnings[0] and "0.1.0" in warnings[0]
    make_wheel(tmp_path / "wheels", version="0.2.0")
    assert installer.check_libraries(registry, {"shared-logging"}) == ([], [])


# --------------------------------------------------------------------------- the shipped repository


def test_the_shipped_wheel_matches_the_workspace_checkout_it_was_built_from():
    registry = load_registry(ROOT / "services.toml")
    (wheel,) = (ROOT / "wheels").glob("shared_logging-*.whl")
    checkout = (ROOT / registry.libraries["shared-logging"]["path"]).resolve()
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


def test_a_fresh_machine_without_the_workspace_can_deploy_every_service(tmp_path):
    """Only this repository was cloned: nothing named ../shared-logging exists next to it."""
    shipped = load_registry(ROOT / "services.toml")
    fresh = replace(shipped, libraries={"shared-logging": {**shipped.libraries["shared-logging"], "path": str(tmp_path / "absent")}})
    kind, _ = installer.library_source(fresh, "shared-logging")
    assert kind == "wheel_dir"
    for example in (ROOT / "hosts").glob("*.example.toml"):
        host = load_host(str(example), fresh, ROOT / "robot.example.toml")
        manager = Manager(Shell(dry_run=True), host, fresh)
        errors, _ = manager.validate(None)
        assert not [e for e in errors if "shared-logging" in e], f"{example.name}: {errors}"


def test_an_unusable_library_stops_the_deploy_before_anything_is_cloned(tmp_path):
    shipped = load_registry(ROOT / "services.toml")
    broken = replace(shipped, libraries={"shared-logging": {"path": str(tmp_path / "absent")}})
    host = load_host(str(ROOT / "hosts" / "all-in-one.example.toml"), broken)
    host = replace(host, workdir=tmp_path / "work")
    with pytest.raises(DeployError, match="shared-logging"):
        Manager(Shell(dry_run=True), host, broken).deploy(None)
    assert not (tmp_path / "work").exists()


def test_every_service_defaults_to_the_branch_that_carries_the_vendored_contracts_wheel():
    registry = load_registry(ROOT / "services.toml")
    assert {spec.branch for spec in registry.services.values()} == {launch.DEFAULT_BRANCH}


# --------------------------------------------------------------------------- remote URLs


def test_a_malformed_remote_url_is_an_error_and_a_loopback_one_a_warning(tmp_path):
    registry = load_registry(ROOT / "services.toml")
    path = tmp_path / "h.toml"
    path.write_text(textwrap.dedent("""
        [services.brain]
        [remote]
        microphone = "ftp://192.168.1.20:8000"
        speaker = "the speaker box"
        stt = "http://127.0.0.1:8001"
        tts = "http://tts-box.lan:8002"
        ai-agent = "http://ai-box.lan:7998"
    """))
    errors, warnings = validate_host(load_host(str(path), registry))
    assert any("microphone" in e and "not an address" in e for e in errors)
    assert any("speaker" in e and "not an address" in e for e in errors)  # a space in an address
    assert not any("tts" in e or "ai-agent" in e for e in errors)
    assert any("stt" in w and "this machine" in w for w in warnings)
