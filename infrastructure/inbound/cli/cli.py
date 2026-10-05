"""Command line: ``python oblivion.py <command> --host <machine>``."""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import sys
from pathlib import Path

from application.dtos.options import Options
from application.services.compat_service import ERROR, OK, WARNING
from application.services.deployment_service import DeploymentService
from application.services.layout_service import describe_layout
from composition_root.container import new_compat_service, new_deployment_service
from domain.errors import DeployError
from domain.rules.branch_overrides import apply_branch_overrides
from domain.rules.env_names import mask
from infrastructure.config.catalogue_loader import load_catalogue
from infrastructure.config.host_loader import load_host
from infrastructure.config.layout_loader import (
    available_layouts, describe_layouts, load_layout, read_robot_file, write_robot_file,
)
from infrastructure.config.paths import PROJECT_ROOT, ConfigPaths
from infrastructure.config.settings_loader import resolved_refs
from infrastructure.outbound.autostart import autostart
from infrastructure.outbound.shell.shell import Shell

COMMANDS = {
    "layouts": "list the ready-made layouts (where each service runs) and show which one config/robot.toml uses",
    "init": "create config/robot.toml: choose a layout and give the address of each machine",
    "topology": "show the whole robot: every machine, its address, its services, what it exposes; check each can find what it needs",
    "plan": "show what this machine will run: services, branches, and every environment value with the file it came from",
    "validate": "check the configuration, service wiring and required settings (no network, no changes)",
    "doctor": "check this machine has what deployment needs (git, python, docker, ...)",
    "deploy": "first install or repair: fetch code, install dependencies, write env, start, health-check",
    "update": "move to the configured (or --branch) code; roll back a service whose new version is unhealthy",
    "start": "start the services",
    "stop": "stop the services",
    "restart": "stop then start",
    "status": "running state, code version and health of each service (--remote also checks other machines)",
    "logs": "print the last lines of a service log (native services)",
    "env": "print the environment of one service (secrets masked) and which file each value came from",
    "compat": "check the services fit together on the branch, tag or commit each will be deployed from (contracts version, ports, pushed code; --remote also checks the git remotes)",
    "autostart": "install/remove/print the boot-time start (systemd user unit, Windows scheduled task)",
}
NO_HOST = ("layouts", "init", "topology", "compat")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oblivion", description="Deploy OBLIVION services on this machine.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")
    for name, help_text in COMMANDS.items():
        p = sub.add_parser(name, help=help_text, description=help_text)
        if name not in NO_HOST:
            p.add_argument("--host", required=True, metavar="MACHINE", help="a machine of the layout in config/robot.toml (see: layouts, topology)")
        p.add_argument("--config", metavar="DIR", help="the config folder to use (default: config/ of this repository)")
        if name not in ("layouts", "init", "topology"):
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
            p.add_argument("--remote", action="store_true", help="also check the services of the other machines")
        if name == "compat":
            p.add_argument("--remote", action="store_true", help="also check that each branch/tag exists on its git remote (needs the network)")
            p.add_argument("--workspace", metavar="DIR", help="the development workspace with a checkout of every service (default: the folder above this repository)")
        if name == "logs":
            p.add_argument("--lines", "-n", type=int, default=50)
        if name == "env":
            p.add_argument("service_name", nargs="?", metavar="SERVICE")
        if name == "autostart":
            p.add_argument("action", choices=["install", "remove", "print"])
        if name == "init":
            p.add_argument("--layout", required=True, metavar="NAME", help="one of: " + (", ".join(available_layouts(ConfigPaths())) or "(no layouts found)"))
            p.add_argument("--address", action="append", default=[], metavar="MACHINE=IP", help="the address of a machine of the layout (repeatable)")
            p.add_argument("--force", action="store_true", help="replace an existing config/robot.toml")
    return parser


def _paths(args: argparse.Namespace) -> ConfigPaths:
    return ConfigPaths(Path(args.config).resolve()) if getattr(args, "config", None) else ConfigPaths()


def _service(args: argparse.Namespace, paths: ConfigPaths) -> DeploymentService:
    catalogue = load_catalogue(paths)
    host = apply_branch_overrides(load_host(args.host, catalogue, paths), getattr(args, "branch", []))
    options = Options(
        force=getattr(args, "force", False),
        system_deps=getattr(args, "system_deps", False),
        rollback=not getattr(args, "no_rollback", False),
        health_timeout=getattr(args, "health_timeout", 60.0),
        skip_health=getattr(args, "no_health", False),
        remote_wait=getattr(args, "remote_wait", 120.0),
    )
    return new_deployment_service(host, catalogue, options, shell=Shell(dry_run=args.dry_run))


def _report(failures: list[str]) -> int:
    if not failures:
        return 0
    print("\nFAILED:")
    for failure in failures:
        print(f"  - {failure}")
    return 1


def _layouts(args: argparse.Namespace) -> int:
    paths = _paths(args)
    print(f"Layouts ({paths.label(paths.layouts)}/): where each service runs. Pick one in {paths.label(paths.robot)}.\n")
    for name, description, machines in describe_layouts(paths):
        print(f"  {name}" + (f"   {description}" if description else ""))
        for machine, services in machines.items():
            print(f"      {machine:<8} {', '.join(services)}")
    if paths.robot.exists():
        print(f"\nIn use: {read_robot_file(paths).layout!r} ({paths.label(paths.robot)})")
    else:
        print(f"\nNo {paths.label(paths.robot)} yet: run  python oblivion.py init --layout <name> --address <machine>=<ip> ...")
    return 0


def _init(args: argparse.Namespace) -> int:
    paths = _paths(args)
    catalogue = load_catalogue(paths)
    addresses: dict[str, str] = {}
    for item in args.address:
        machine, sep, address = item.partition("=")
        if not sep or not machine or not address:
            raise DeployError(f"--address {item!r}: write it as MACHINE=IP, e.g. --address pi=192.168.1.20")
        addresses[machine.strip()] = address.strip()
    path = write_robot_file(paths, args.layout, addresses, overwrite=args.force)
    try:
        layout = load_layout(paths, catalogue)
    except DeployError:
        path.unlink(missing_ok=True) if not args.force else None
        raise
    print(f"wrote {paths.label(path)}: layout {layout.name!r}")
    for machine in layout.machines.values():
        print(f"  {machine.name:<8} {machine.address:<16} {', '.join(machine.services)}")
    print("\nNext: python oblivion.py topology   (check it),  then on each machine:  python oblivion.py deploy --host <machine>")
    return 0


def _topology(args: argparse.Namespace) -> int:
    paths = _paths(args)
    catalogue = load_catalogue(paths)
    layout = load_layout(paths, catalogue)
    hosts = {name: load_host(name, catalogue, paths, layout) for name in layout.machines}
    lines, problems = describe_layout(layout, catalogue, hosts)
    print("\n".join(lines))
    return 1 if problems else 0


def _compat(args: argparse.Namespace) -> int:
    paths = _paths(args)
    catalogue = load_catalogue(paths)
    workspace = Path(args.workspace).resolve() if args.workspace else PROJECT_ROOT.parent
    names = args.service
    unknown = [n for n in names or () if n not in catalogue.services]
    if unknown:
        raise DeployError(f"unknown service(s) {', '.join(unknown)} (known: {', '.join(sorted(catalogue.services))})")
    findings = new_compat_service(catalogue).run(resolved_refs(paths, catalogue), workspace, remote=args.remote, names=names)
    marks = {OK: "[ok]   ", WARNING: "[warn] ", ERROR: "[FAIL] "}
    for finding in findings:
        print(f"{marks[finding.level]}{finding.service:<10} {finding.message}")
    errors = sum(1 for f in findings if f.level == ERROR)
    warnings = sum(1 for f in findings if f.level == WARNING)
    print("\nOK" if not errors else f"\n{errors} error(s)", f"({warnings} warning(s))")
    return 1 if errors else 0


def run(args: argparse.Namespace) -> int:
    command = args.command
    if command == "layouts":
        return _layouts(args)
    if command == "init":
        return _init(args)
    if command == "topology":
        return _topology(args)
    if command == "compat":
        return _compat(args)

    service = _service(args, _paths(args))
    names: list[str] | None = args.service

    if command == "plan":
        print("\n".join(service.plan_lines(names)))
        return 0
    if command == "validate":
        errors, warnings = service.validate(names)
        for warning in warnings:
            print(f"warning: {warning}")
        for error in errors:
            print(f"error:   {error}")
        print("OK" if not errors else f"{len(errors)} error(s)")
        return 1 if errors else 0
    if command == "doctor":
        return _doctor(service)
    if command == "deploy":
        return _report(service.deploy(names))
    if command == "update":
        return _report(service.update(names))
    if command == "start":
        return _report(service.start(names))
    if command == "stop":
        service.stop(names)
        return 0
    if command == "restart":
        service.stop(names)
        return _report(service.start(names))
    if command == "status":
        rows = service.status(names, args.remote)
        width = max((len(r[0]) for r in rows), default=8)
        for name, state, detail in rows:
            print(f"{name:<{width}}  {state:<11} {detail}")
        return 0 if all(r[1] == "running" for r in rows) else 1
    if command == "logs":
        for name in service.select(names):
            path = service.host.log_file(name)
            print(f"== {name} ({path})")
            if path.exists():
                print("\n".join(path.read_text(errors="replace").splitlines()[-args.lines:]))
        return 0
    if command == "env":
        target = args.service_name or (names[0] if names else None)
        if target is None:
            raise DeployError("env needs a service name")
        resolved = service.resolve(target)
        for key, value in sorted(resolved.values.items()):
            print(f"{key}={mask(key, value)}    # {resolved.layer_of[key]}")
        for problem in resolved.errors:
            print(f"error: {problem}")
        return 1 if resolved.errors else 0
    if command == "autostart":
        host = service.host
        autostart.require_supported(host)
        if args.action == "print":
            print(autostart.systemd_unit(host) if host.os_family == "linux" else " ".join(autostart.schtasks_command(host)))
        elif args.action == "install":
            autostart.install(service.shell, host)
        else:
            autostart.remove(service.shell, host)
        return 0
    raise DeployError(f"unknown command {command}")


def _doctor(service: DeploymentService) -> int:
    host = service.host
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
        all(importlib.util.find_spec(module) is not None for module in ("venv", "ensurepip")),
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
    return probe.exists() and os.access(probe, os.W_OK)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except DeployError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
