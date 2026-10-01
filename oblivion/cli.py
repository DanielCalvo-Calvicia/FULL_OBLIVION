"""Command line: ``oblivion <command> --host <machine>``."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import autostart
from .config import (
    ROBOT_FILE, DeployError, apply_branch_overrides, exposed_services, load_host, load_registry, load_topology,
    validate_host,
)
from .manager import Manager, Options
from .shell import Shell

ROOT = Path(__file__).resolve().parent.parent
COMMANDS = {
    "topology": "show the whole robot: every machine, its address, its services, what it exposes; check each can find what it needs",
    "plan": "show what this machine will run: services, branches, and every environment value with its origin",
    "validate": "check the host file, service wiring and required environment values (no network, no changes)",
    "doctor": "check this machine has what deployment needs (git, python, docker, ...)",
    "deploy": "first install or repair: fetch code, install dependencies, write env, start, health-check",
    "update": "move to the configured (or --branch) code; roll back a service whose new version is unhealthy",
    "start": "start the services",
    "stop": "stop the services",
    "restart": "stop then start",
    "status": "running state, code version and health of each service (--remote also checks other machines)",
    "logs": "print the last lines of a service log (native services)",
    "env": "print the environment of one service (secrets masked)",
    "autostart": "install/remove/print the boot-time start (systemd user unit, Windows scheduled task)",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oblivion", description="Deploy OBLIVION services on this machine.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")
    for name, help_text in COMMANDS.items():
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.add_argument(
            "--host", required=name != "topology", metavar="NAME|FILE",
            help="a machine of robot.toml, hosts/NAME.toml, or a path to a host file",
        )
        p.add_argument(
            "--robot", metavar="FILE",
            help=f"the single file of truth: machines, services and every setting (default {ROBOT_FILE})",
        )
        p.add_argument("--service", "-s", action="append", metavar="NAME", help="limit to this service (repeatable)")
        p.add_argument("--dry-run", action="store_true", help="print what would be done, change nothing")
        if name in ("deploy", "update", "plan", "validate", "env", "start", "restart"):
            p.add_argument(
                "--branch", "-b", action="append", default=[], metavar="[SERVICE=]REF",
                help="branch, tag or commit for every service, or for one with SERVICE=REF (repeatable)",
            )
        if name in ("deploy", "update", "start", "restart"):
            p.add_argument(
                "--remote-wait", type=float, default=120.0, metavar="SECONDS",
                help="before starting a service, wait up to this long for the services of other machines it needs "
                     "(default 120; 0 = do not wait). Brain exits if they are not up within its own preflight",
            )
        if name in ("deploy", "update"):
            p.add_argument("--force", action="store_true", help="overwrite local modifications in the fetched code")
            p.add_argument("--system-deps", action="store_true", help="apt-get install the packages a service needs (Linux/Pi)")
            p.add_argument("--no-health", action="store_true", help="do not wait for the services to become healthy")
            p.add_argument("--health-timeout", type=float, default=60.0, metavar="SECONDS")
        if name == "update":
            p.add_argument("--no-rollback", action="store_true", help="leave a failed update in place")
        if name == "status":
            p.add_argument("--remote", action="store_true", help="also check the services of [remote]")
        if name == "logs":
            p.add_argument("--lines", "-n", type=int, default=50)
        if name == "env":
            p.add_argument("service_name", nargs="?", metavar="SERVICE")
        if name == "autostart":
            p.add_argument("action", choices=["install", "remove", "print"])
    return parser


def _manager(args: argparse.Namespace) -> Manager:
    registry = load_registry(ROOT / "services.toml")
    topology_file = Path(args.robot).resolve() if getattr(args, "robot", None) else None
    host = apply_branch_overrides(load_host(args.host, registry, topology_file), getattr(args, "branch", []))
    options = Options(
        force=getattr(args, "force", False),
        system_deps=getattr(args, "system_deps", False),
        rollback=not getattr(args, "no_rollback", False),
        health_timeout=getattr(args, "health_timeout", 60.0),
        skip_health=getattr(args, "no_health", False),
        remote_wait=getattr(args, "remote_wait", 120.0),
    )
    return Manager(Shell(dry_run=args.dry_run), host, registry, options)


def _report(failures: list[str]) -> int:
    if not failures:
        return 0
    print("\nFAILED:")
    for failure in failures:
        print(f"  - {failure}")
    return 1


def _topology(args: argparse.Namespace) -> int:
    registry = load_registry(ROOT / "services.toml")
    path = Path(args.robot).resolve() if args.robot else ROOT / ROBOT_FILE
    topology = load_topology(path, registry)
    if topology is None:
        raise DeployError(f"no robot file at {path}: copy robot.example.toml to {ROBOT_FILE} and fill it in")
    print(f"{path.name}: {len(topology.machines)} machines")
    problems = 0
    for machine in topology.machines.values():
        host = load_host(machine.name, registry, path, from_topology=True)
        exposed = exposed_services(topology, registry, machine)
        print(f"\n  {machine.name}  {machine.address}   bind {host.bind}")
        for service, instance in host.services.items():
            marker = "  <- called from other machines" if service in exposed else ""
            print(f"      runs   {service:<10} port {instance.port}{marker}")
        consumed = {target for service in host.services for target in registry.services[service].consumes}
        for service in sorted(consumed & set(host.remote)):
            print(f"      calls  {service:<10} {host.remote[service]}")
        errors, _ = validate_host(host)
        for error in errors:
            problems += 1
            print(f"      ERROR  {error}")
    unplaced = sorted(set(registry.services) - {s for m in topology.machines.values() for s in m.services})
    if unplaced:
        print(f"\n  not placed on any machine: {', '.join(unplaced)}")
    print("\nOK" if not problems else f"\n{problems} error(s)")
    return 1 if problems else 0


def run(args: argparse.Namespace) -> int:
    if args.command == "topology":
        return _topology(args)
    manager = _manager(args)
    names: list[str] | None = args.service
    command = args.command

    if command == "plan":
        print("\n".join(manager.plan_lines(names)))
        return 0
    if command == "validate":
        errors, warnings = manager.validate(names)
        for warning in warnings:
            print(f"warning: {warning}")
        for error in errors:
            print(f"error:   {error}")
        print("OK" if not errors else f"{len(errors)} error(s)")
        return 1 if errors else 0
    if command == "doctor":
        return _doctor(manager)
    if command == "deploy":
        return _report(manager.deploy(names))
    if command == "update":
        return _report(manager.update(names))
    if command == "start":
        return _report(manager.start(names))
    if command == "stop":
        manager.stop(names)
        return 0
    if command == "restart":
        manager.stop(names)
        return _report(manager.start(names))
    if command == "status":
        rows = manager.status(names, args.remote)
        width = max((len(r[0]) for r in rows), default=8)
        for name, state, detail in rows:
            print(f"{name:<{width}}  {state:<11} {detail}")
        return 0 if all(r[1] == "running" for r in rows) else 1
    if command == "logs":
        for name in manager.select(names):
            path = manager.host.log_file(name)
            print(f"== {name} ({path})")
            if path.exists():
                print("\n".join(path.read_text(errors="replace").splitlines()[-args.lines:]))
        return 0
    if command == "env":
        target = args.service_name or (names[0] if names else None)
        if target is None:
            raise DeployError("env needs a service name")
        from .envfile import mask
        resolved = manager.resolve(target)
        for key, value in sorted(resolved.values.items()):
            print(f"{key}={mask(key, value)}    # {resolved.layer_of[key]}")
        for problem in resolved.errors:
            print(f"error: {problem}")
        return 1 if resolved.errors else 0
    if command == "autostart":
        autostart.require_supported(manager.host)
        if args.action == "print":
            print(autostart.systemd_unit(manager.host) if manager.host.os_family == "linux" else " ".join(autostart.schtasks_command(manager.host)))
        elif args.action == "install":
            autostart.install(manager.shell, manager.host)
        else:
            autostart.remove(manager.shell, manager.host)
        return 0
    raise DeployError(f"unknown command {command}")


def _doctor(manager: Manager) -> int:
    host = manager.host
    problems = 0

    def check(label: str, ok: bool, hint: str = "") -> None:
        nonlocal problems
        print(f"[{'ok' if ok else 'FAIL'}] {label}" + ("" if ok or not hint else f"  -> {hint}"))
        problems += 0 if ok else 1

    check(f"python {sys.version_info.major}.{sys.version_info.minor} (need 3.11+)", sys.version_info >= (3, 11))
    check("git available", shutil.which("git") is not None, "install git")
    # Debian and Raspberry Pi OS ship the venv module without ensurepip until python3-venv is installed
    check(
        "venv and ensurepip (virtualenvs can be created)",
        all(__import__("importlib.util").util.find_spec(module) is not None for module in ("venv", "ensurepip")),
        "on Debian/Pi: sudo apt install python3-venv",
    )
    if any(i.runtime == "docker" for i in host.services.values()):
        check("docker available", shutil.which("docker") is not None, "install Docker or use runtime = \"native\"")
    check(f"workdir {host.workdir} writable", _writable(host.workdir))
    for name, instance in host.services.items():
        if instance.spec.apt and host.os_family == "linux":
            print(f"[info] {name} may need apt packages: {' '.join(instance.spec.apt)} (deploy --system-deps)")
        if instance.spec.audio:
            print(f"[info] {name} needs a sound device on this machine")
    return 1 if problems else 0


def _writable(path: Path) -> bool:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe.exists() and __import__("os").access(probe, __import__("os").W_OK)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except DeployError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
