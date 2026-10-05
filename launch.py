#!/usr/bin/env python3
"""Launch the whole OBLIVION application on this machine (Windows, Linux or Raspberry Pi).

    python launch.py                 first run: deploys, starts, shows status
                                     later runs: updates to the newest code of the branch, restarts, shows status
    python launch.py stop            stop everything
    python launch.py status          state, code version and health of every service
    python launch.py logs [service]  last log lines (default: brain)

Options:  --branch REF   branch/tag/commit for every service for this run (default: the catalogue's, feature_ai_claude_2)
          --machine NAME which machine of the layout this is (only needed when the layout has several)
          --stt local    use local Whisper instead of the OpenAI API (no key needed, big install; first run only)
          --no-update    start what is installed, do not fetch new code
          --console M    what each service window prints (Windows): stream (default, errors + stream events),
                         errors (errors only) or all. The log files always keep everything.
          --system-deps  Linux/Pi: apt-get install the system packages the services need (uses sudo)
          --dry-run      print every command, change nothing

It only needs Python 3.11+ and git. WITH a config/robot.toml (which layout, where each machine is) it deploys that machine and
creates nothing: the settings and keys come from config/. WITHOUT one it creates, on the first run, config/robot.toml (layout
all-in-one: every service on this machine) and your keys in config/local/ (git-ignored), and never overwrites a file you have.
For several machines use oblivion.py, one `--host <machine>` per machine (see README.md).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import tomllib
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("launch.py needs Python 3.11 or newer (found %d.%d)" % sys.version_info[:2])

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from application.dtos.options import Options  # noqa: E402
from application.services.deployment_service import DeploymentService  # noqa: E402
from composition_root.container import new_deployment_service  # noqa: E402
from domain.errors import DeployError  # noqa: E402
from domain.rules.branch_overrides import apply_branch_overrides  # noqa: E402
from domain.rules.env_names import is_secret  # noqa: E402
from infrastructure.config.catalogue_loader import load_catalogue  # noqa: E402
from infrastructure.config.host_loader import load_host  # noqa: E402
from infrastructure.config.layout_loader import load_layout, write_robot_file  # noqa: E402
from infrastructure.config.paths import ConfigPaths  # noqa: E402
from infrastructure.outbound.shell.shell import Shell  # noqa: E402

DEFAULT_BRANCH = "feature_ai_claude_2"
GENERATED_LAYOUT = "all-in-one"  # what a first run without config/robot.toml uses: every service on this machine
PATHS = ConfigPaths()
# Everything the catalogue knows: ai-agent's LLM provider keys (which launch.py copies from the environment into
# config/local/ai-agent.toml). Nothing about them is repeated here.
CATALOGUE = load_catalogue(PATHS)
SERVICES = tuple(CATALOGUE.services)
AI_AGENT_KEYS = tuple(key for key in CATALOGUE.services["ai-agent"].require_any if is_secret(key))


def _shown(path: Path) -> str:
    return PATHS.label(path)


def robot_machine(args: argparse.Namespace) -> str | None:
    """The machine of the layout this launch is for; None when there is no config/robot.toml yet (a first run creates it)."""
    wanted = getattr(args, "machine", None)
    if not PATHS.robot.exists():
        if wanted:
            raise DeployError(
                f"--machine {wanted} needs a {_shown(PATHS.robot)}: run  python oblivion.py init --layout <name>  "
                "(layouts: python oblivion.py layouts)"
            )
        return None
    layout = load_layout(PATHS, CATALOGUE)
    machines = list(layout.machines)
    if wanted:
        if wanted not in machines:
            raise DeployError(f"machine {wanted!r} is not in layout {layout.name!r} (has: {', '.join(machines)})")
        return wanted
    if len(machines) == 1:
        return machines[0]
    raise DeployError(
        f"layout {layout.name!r} has {len(machines)} machines ({', '.join(machines)}): say which one this is, "
        f"e.g.  python launch.py --machine {machines[0]}"
    )


# --------------------------------------------------------------------------- the files a first run creates


def local_env(name: str) -> dict[str, str]:
    """The ``[env]`` of ``config/local/<name>.toml`` (empty when the file does not exist)."""
    path = PATHS.local / f"{name}.toml"
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            return {str(k): str(v) for k, v in tomllib.load(handle).get("env", {}).items()}
    except tomllib.TOMLDecodeError as error:
        raise DeployError(f"{path}: invalid TOML: {error}") from error


def has_local_key(service: str, key: str) -> bool:
    """Whether ``key`` is already set for ``service`` in its own local file or in the shared local/all.toml."""
    return bool(local_env(service).get(key) or local_env("all").get(key))


def write_local_file(name: str, env: dict[str, str]) -> Path:
    """Create ``config/local/<name>.toml`` readable by this user only. Never called for a file that exists."""
    path = PATHS.local / f"{name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Written by launch.py. Edit freely: launch.py never overwrites an existing file.", "[env]"]
    lines += [f"{key} = {json.dumps(value)}" for key, value in env.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)  # it holds API keys: readable by this user only (no effect on Windows)
    except OSError:
        pass
    return path


def ensure_files(stt_engine: str, dry_run: bool, interactive: bool) -> list[str]:
    """Create config/robot.toml and the local key files when missing. Returns notes for the operator."""
    notes: list[str] = []
    if not PATHS.robot.exists():
        notes.append(f"created {_shown(PATHS.robot)} (layout {GENERATED_LAYOUT!r}: every service on this machine)")
        write_robot_file(PATHS, GENERATED_LAYOUT, {})  # also in a dry run: it is a git-ignored config file

    stt_file = PATHS.local / "stt.toml"
    if stt_engine == "local":
        if not stt_file.exists():  # also in a dry run: no secret in it, and the dry run needs it to see the same settings
            write_local_file("stt", {"STT_ENGINE": "local"})
            notes.append(f"created {_shown(stt_file)} (STT_ENGINE = local)")
    elif not has_local_key("stt", "OPENAI_API_KEY") and local_env("stt").get("STT_ENGINE") != "local":
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key and interactive and not dry_run:
            key = getpass.getpass(f"OpenAI API key for speech-to-text (input hidden, stored only in {_shown(stt_file)}): ").strip()
        if not key and not dry_run:
            raise DeployError(
                "STT needs an OpenAI API key. Set the OPENAI_API_KEY environment variable and run again, "
                f"or put OPENAI_API_KEY = \"...\" under [env] in {_shown(stt_file)}, or run with --stt local"
            )
        if key and not dry_run:
            if stt_file.exists():
                raise DeployError(f"{_shown(stt_file)} exists but has no OPENAI_API_KEY: add  OPENAI_API_KEY = \"...\"  under its [env]")
            write_local_file("stt", {"OPENAI_API_KEY": key})
            notes.append(f"stored the key in {_shown(stt_file)} (git-ignored)")

    if not dry_run:
        agent_file = PATHS.local / "ai-agent.toml"
        missing = [key for key in AI_AGENT_KEYS if os.environ.get(key, "").strip() and not has_local_key("ai-agent", key)]
        if missing and not agent_file.exists():
            write_local_file("ai-agent", {key: os.environ[key].strip() for key in missing})
            notes.append(f"copied {', '.join(missing)} from the environment into {_shown(agent_file)} for ai-agent (git-ignored)")
        elif missing:
            notes.append(f"warning: {_shown(agent_file)} exists, so {', '.join(missing)} from the environment were not added: put them under its [env]")
        if not any(has_local_key("ai-agent", key) for key in AI_AGENT_KEYS):
            notes.append(
                "warning: no LLM provider key for ai-agent: export GROQ_API_KEY / GOOGLE_API_KEY and run again, "
                f"or add GROQ_API_KEY = \"...\" under [env] in {_shown(agent_file)}. Without one ai-agent is not available"
            )
    return notes


# --------------------------------------------------------------------------- the commands


def build_manager(args: argparse.Namespace) -> DeploymentService:
    machine = robot_machine(args)
    if machine is None:
        raise DeployError("nothing deployed yet: run  python launch.py  first")
    host = load_host(machine, CATALOGUE, PATHS)
    if args.branch:
        host = apply_branch_overrides(host, [args.branch])
    options = Options(
        system_deps=getattr(args, "system_deps", False),
        health_timeout=getattr(args, "health_timeout", 180.0),
    )
    return new_deployment_service(host, CATALOGUE, options, shell=Shell(dry_run=args.dry_run))


def print_status(service: DeploymentService) -> int:
    rows = service.status(None, False)
    width = max(len(r[0]) for r in rows)
    print()
    for name, state, detail in rows:
        print(f"  {name:<{width}}  {state:<10} {detail}")
    return 0 if all(r[1] == "running" for r in rows) else 1


def cmd_up(args: argparse.Namespace) -> int:
    interactive = sys.stdin.isatty()
    os.environ["OBLIVION_CONSOLE_FILTER"] = args.console  # read by the console wrapper (tee.py) in each service window
    if PATHS.robot.exists():
        if args.stt == "local":
            raise DeployError(
                f'--stt local only shapes the first run: with a {_shown(PATHS.robot)} set STT_ENGINE = "local" under [env] in config/local/stt.toml'
            )
        layout = load_layout(PATHS, CATALOGUE)
        print(f"Using {_shown(PATHS.robot)}: layout {layout.name!r}, machine {robot_machine(args)!r} (settings and keys come from config/)")
    else:
        for note in ensure_files(args.stt, args.dry_run, interactive):
            print(note)
    service = build_manager(args)
    if not args.dry_run:
        errors, warnings = service.validate(None)
        for warning in warnings:
            print(f"warning: {warning}")
        if errors:
            raise DeployError("cannot launch:\n  " + "\n  ".join(errors))

    installed = all(service.state.get(name).get("commit") for name in service.host.services)
    if installed and args.no_update:
        print("Starting the installed services (--no-update)")
        failures = service.start(None)
    elif installed:
        print("Updating to the newest code of the branch and restarting")
        failures = service.update(None)  # also starts every service, healthy or rolled back
    else:
        print("First run: fetching code and installing dependencies (a few minutes)")
        failures = service.deploy(None)

    if not args.dry_run:
        print_status(service)
    if failures:
        print("\nFAILED:")
        for failure in failures:
            print(f"  - {failure}")
        print("\nSee the reason with:  python launch.py logs <service>")
        return 1
    if not args.dry_run:
        print(
            "\nAll services are up. Brain now opens the voice pipeline: use HEADPHONES, say a sentence and pause "
            "about two seconds; you should hear it repeated.\n"
            "  python launch.py logs      Brain's log (which hop is active)\n"
            "  python launch.py stop      stop everything"
        )
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    build_manager(args).stop(None)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    return print_status(build_manager(args))


def cmd_logs(args: argparse.Namespace) -> int:
    service = build_manager(args)
    name = args.service
    if name not in service.host.services:
        raise DeployError(f"unknown service {name!r}; known: {', '.join(service.host.services)}")
    path = service.host.log_file(name)
    print(f"== {name} ({path})")
    if path.exists():
        print("\n".join(path.read_text(errors="replace").splitlines()[-args.lines:]))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="launch.py", description=(__doc__ or "").split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help="print every command, change nothing")
    sub = parser.add_subparsers(dest="command")
    dry = argparse.ArgumentParser(add_help=False)
    dry.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    dry.add_argument("--machine", metavar="NAME", default=argparse.SUPPRESS, help="the machine of the layout this is")
    up = sub.add_parser("up", parents=[dry], help="deploy or update, start everything (default)")
    up.add_argument("--branch", metavar="REF", help=f"branch, tag or commit for every service (default: {DEFAULT_BRANCH})")
    up.add_argument("--stt", choices=["openai", "local"], default="openai", help="speech-to-text engine")
    up.add_argument("--no-update", action="store_true", help="start what is installed; do not fetch new code")
    up.add_argument(
        "--console", choices=["stream", "errors", "all"], default=os.environ.get("OBLIVION_CONSOLE_FILTER", "stream"),
        help="what each service window prints (Windows): errors + stream events (default), errors only, or everything",
    )
    up.add_argument("--system-deps", action="store_true", help="Linux/Pi: apt-get install the packages services need")
    up.add_argument("--health-timeout", type=float, default=180.0, metavar="SECONDS")
    sub.add_parser("stop", parents=[dry], help="stop everything")
    sub.add_parser("status", parents=[dry], help="state and health of every service")
    logs = sub.add_parser("logs", parents=[dry], help="print the last log lines of a service")
    logs.add_argument("service", nargs="?", default="brain")
    logs.add_argument("--lines", "-n", type=int, default=60)
    return parser


COMMANDS = ("up", "stop", "status", "logs")


def normalize(argv: list[str]) -> list[str]:
    """``launch.py --branch X`` (no command) means ``launch.py up --branch X``."""
    if any(arg in COMMANDS for arg in argv) or any(arg in ("-h", "--help") for arg in argv):
        return argv
    dry_run = [arg for arg in argv if arg == "--dry-run"]
    return [*dry_run, "up", *[arg for arg in argv if arg != "--dry-run"]]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(normalize(sys.argv[1:] if argv is None else argv))
    args.branch = getattr(args, "branch", None)
    try:
        if not PATHS.robot.exists() and args.command in ("stop", "status", "logs"):
            raise DeployError("nothing deployed yet: run  python launch.py  first")
        return {"up": cmd_up, "stop": cmd_stop, "status": cmd_status, "logs": cmd_logs}[args.command](args)
    except DeployError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
