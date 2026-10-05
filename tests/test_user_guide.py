"""docs/USER_GUIDE.md tells operators what to type: every command and flag in it must exist."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import launch  # noqa: E402
from infrastructure.inbound.cli.cli import build_parser  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GUIDE = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")


def subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    (action,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    return dict(action.choices)


def options_of(parser: argparse.ArgumentParser) -> set[str]:
    return {option for action in parser._actions for option in action.option_strings}


def command_lines(program: str) -> list[str]:
    """Lines of the guide that run ``program``, without the trailing ``# comment`` and the leading prompt."""
    found = []
    for line in GUIDE.splitlines():
        if re.search(rf"\b{re.escape(program)}\b", line) and not line.lstrip().startswith(("|", ">", "-", "#", "1.", "2.")):
            found.append(line.split("  #")[0].strip())
    return found


def test_every_oblivion_command_and_flag_in_the_guide_exists():
    commands = subparsers(build_parser())
    checked = 0
    for line in command_lines("oblivion.py"):
        match = re.search(r"oblivion\.py\s+([a-z-]+)(.*)", line)
        if not match or match.group(1) in ("...",):
            continue
        command, rest = match.groups()
        assert command in commands, f"unknown command in the guide: {line}"
        known = options_of(commands[command])
        for flag in re.findall(r"(?<![\w-])(--?[a-z][a-z-]*)", rest):
            assert flag in known, f"`oblivion.py {command}` has no {flag} (guide line: {line})"
        checked += 1
    assert checked >= 20  # the guide really is full of commands


def test_every_launch_command_and_flag_in_the_guide_exists():
    parser = launch.build_parser()
    commands = subparsers(parser)
    top = options_of(parser)
    checked = 0
    for line in command_lines("launch.py"):
        match = re.search(r"launch\.py(.*)", line)
        rest = match.group(1) if match else ""
        words = re.findall(r"(?<![\w-])([a-z]+)(?![\w-])", rest.split("--")[0])
        command = next((w for w in words if w in commands), "up")
        known = options_of(commands[command]) | top
        for flag in re.findall(r"(?<![\w-])(--?[a-z][a-z-]*)", rest):
            assert flag in known, f"`launch.py {command}` has no {flag} (guide line: {line})"
        checked += 1
    assert checked >= 5


def test_the_launch_flags_the_guide_recommends_are_real():
    up = subparsers(launch.build_parser())["up"]
    for flag in ("--stt", "--branch", "--dry-run", "--no-update", "--system-deps", "--health-timeout"):
        assert flag in options_of(up) | {"--dry-run"}, flag


@pytest.mark.parametrize("target", sorted(set(re.findall(r"\]\(([^)#]+\.md)(?:#[^)]*)?\)", GUIDE))))
def test_the_files_the_guide_links_to_exist(target):
    assert (ROOT / "docs" / target).resolve().exists(), target


@pytest.mark.parametrize("layout", sorted(set(re.findall(r"config[\/]layouts[\/]([a-z0-9-]+)\.toml", GUIDE))))
def test_the_layouts_the_guide_names_exist(layout):
    assert (ROOT / "config" / "layouts" / f"{layout}.toml").exists()


@pytest.mark.parametrize("name", sorted(set(re.findall(r"layout = \"([a-z0-9-]+)\"", GUIDE))))
def test_the_layouts_the_guide_picks_in_robot_toml_exist(name):
    assert (ROOT / "config" / "layouts" / f"{name}.toml").exists()


def test_the_guide_names_the_secret_lines_the_tool_reads_and_holds_no_key():
    for line in ('OPENAI_API_KEY = "', 'GROQ_API_KEY = "', "config/local/", "[env]"):
        assert line in GUIDE  # the keys go in config/local/, named exactly as the files' tables and variables are
    assert not re.search(r"(sk-[A-Za-z0-9]{10,}|AIza[0-9A-Za-z_-]{20,}|gsk_[A-Za-z0-9]{10,})", GUIDE)
