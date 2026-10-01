"""Inventory of every environment variable of every deployable service, and the complete robot file built from it.

    brain_microservice/windows/Scripts/python.exe deployment/scripts/env_inventory.py            # print the template
    brain_microservice/windows/Scripts/python.exe deployment/scripts/env_inventory.py --write    # refresh robot.example.toml
    brain_microservice/windows/Scripts/python.exe deployment/scripts/env_inventory.py --check    # fail if it is out of date

Needs the development workspace next to this repository (it reads each service's source). The committed
``robot.example.toml`` is what an operator copies to ``robot.toml``: the machines and every setting and key of every
service in ONE file; ``tests/test_env_inventory.py`` fails when it no longer lists everything the services read.

A variable comes from the union of: the service's ``.env.example`` (live and commented-out lines), the variables its code
reads, the shared-logging variables every service reads, and the few names the code builds dynamically (``EXTRA``).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from fnmatch import fnmatchcase
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oblivion.config import Registry, ServiceSpec, load_registry  # noqa: E402
from oblivion.envfile import SHARED_LOGGING_VARS, TUNING_VARS, computed_variables, is_secret  # noqa: E402
from oblivion.envparse import parse_env  # noqa: E402

WORKSPACE = ROOT.parent
TEMPLATE = ROOT / "robot.example.toml"
SKIP_DIRS = {"windows", "vendor", "tests", "testclear", "__pycache__", ".git", "node_modules", "old", "build", "dist"}

# Variables of shared-logging: every service reads them, so ALL__<NAME> sets one for all services at once.
SHARED = {
    "LOG_LEVEL": ("INFO", "TRACE, DEBUG, INFO, WARNING, ERROR or CRITICAL"),
    "LOG_FORMAT": ("json", "json (machine-readable) or console (key=value lines for people)"),
    "LOG_OUTPUT": ("stdout", "stdout, stderr or a file path"),
    "APP_ENV": ("development", "development, staging or production: the label on every log line and span"),
    "ENVIRONMENT": ("", "same as APP_ENV and wins over it when both are set"),
    "TRACE_EXPORT_ENABLED": ("false", "send trace spans to a collector"),
    "TRACE_EXPORT_URL": ("", "endpoint that receives the spans (enabled without a URL stays disabled)"),
    "TRACE_EXPORT_HEADERS": ("", "extra request headers, Name=value,Name2=value2 (may carry a credential)"),
    "TRACE_EXPORT_ATTRIBUTES": ("", "extra span attribute names allowed to leave the process, comma separated"),
}
assert set(SHARED) == set(SHARED_LOGGING_VARS) - TUNING_VARS, "keep SHARED in step with oblivion/envfile.py"

# Names the code builds at run time or reads through an alias, which no search of the source can find.
EXTRA: dict[str, dict[str, tuple[str, str]]] = {
    "ai-agent": {
        "AI_AGENT_MODELS_FILE": ("config/step_models.json", "another file with the model choice per step (profiles)"),
        "GITHUB_API_KEY": ("", "alias of GITHUB_PAT"),
        **{
            f"AI_AGENT_MODEL_PHASE_{n}": ("", f"model id for phase {n}, wins over the models file ({label})")
            for n, label in ((1, "triage"), (2, "project manager"), (3, "safety gate"), (4, "worker"), (5, "MCP operator"),
                             (6, "data engineer"), (7, "draft writer"), (8, "editor in chief"), (9, "answer checker"),
                             (20, "motion planner, the movement agent"), (99, "clarification"))
        },
    },
}

_NAME = r"[\"']([A-Z][A-Z0-9_]{2,})[\"']"
_READS = re.compile(
    r"(?:getenv|environ\.get|environ\[|\benv\.get|\benv|_int_env|_float_env|_bool_env|_base_url|_endpoint|_env)\(?\[?\s*" + _NAME
)
_FALLBACK = re.compile(r"fallback_env_name\s*=\s*" + _NAME)
_CONSTANT = re.compile(r"^[A-Z_]*(?:VARIABLE|ENV_VAR)S?\s*=\s*" + _NAME, re.M)
_COMMENTED = re.compile(r"^#\s?([A-Z][A-Z0-9_]{2,})=(.*)$")


@dataclass
class Variable:
    name: str
    default: str | None = None  # None: the code decides
    help: str = ""
    sources: set[str] = field(default_factory=set)


_GENERIC_COMMENT = re.compile(r"^(copy to|never commit|variables already set|--- |runtime environment)", re.I)


def _clean(parts: list[str]) -> str:
    """The comment lines above a variable, minus file-header boilerplate, as one sentence of at most ~200 characters."""
    kept = [p for p in parts if p and not _GENERIC_COMMENT.match(p)]
    return textwrap.shorten(" ".join(kept), width=200, placeholder=" ...")


def parse_example(text: str) -> dict[str, Variable]:
    """Variables of a ``.env.example``: live lines and commented-out ``# NAME=value`` lines, with the comment above."""
    found: dict[str, Variable] = {}
    comment: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            comment = []
            continue
        commented = _COMMENTED.match(line)
        if line.startswith("#") and not commented:
            comment.append(line.lstrip("# ").strip())
            continue
        if commented:
            name, value = commented.group(1), commented.group(2)
            parsed = parse_env(f"{name}={value}").get(name, "")
        elif "=" in line:
            name = line.partition("=")[0].strip().removeprefix("export ").strip()
            parsed = parse_env(line).get(name, "")
            value = line.partition("=")[2]
        else:
            continue
        inline = re.search(r"\s#\s*(.*)$", value)
        block = comment if len(comment) <= 3 else []  # a longer block describes a group of variables, not this one
        found[name] = Variable(name, parsed, _clean([*block, inline.group(1).strip() if inline else ""]), {"example"})
        comment = []
    return found


def code_variables(folder: Path) -> set[str]:
    names: set[str] = set()
    for path in folder.rglob("*.py"):
        if SKIP_DIRS & set(path.relative_to(folder).parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in (_READS, _FALLBACK, _CONSTANT):
            names |= set(pattern.findall(text))
    return names


def inventory(registry: Registry, workspace: Path = WORKSPACE) -> dict[str, dict[str, Variable]]:
    """``{service: {variable: Variable}}`` for every deployable service (computed and shared variables excluded)."""
    result: dict[str, dict[str, Variable]] = {}
    for name, spec in registry.services.items():
        folder = workspace / spec.repo_dir
        variables: dict[str, Variable] = {}
        example = folder / ".env.example"
        if example.exists():
            variables = parse_example(example.read_text(encoding="utf-8"))
        for code_name in code_variables(folder):
            variables.setdefault(code_name, Variable(code_name)).sources.add("code")
        for extra, (default, help_text) in EXTRA.get(name, {}).items():
            variable = variables.setdefault(extra, Variable(extra))
            variable.default = variable.default if variable.default is not None else default
            variable.help = help_text  # the hand-written text: the parsed one may belong to a neighbour
            variable.sources.add("extra")
        for key, value in spec.env.items():  # services.toml sets it, so that is what a deployed machine gets
            variable = variables.setdefault(key, Variable(key))
            variable.default = value
            variable.help = f"{variable.help} (services.toml presets {key}={value})".strip()
            variable.sources.add("registry")
        for hidden in SHARED_LOGGING_VARS | computed_variables(spec):
            variables.pop(hidden, None)  # shared-logging names are in the ALL section; the rest the tool computes
        for key in [k for k in variables if _internal(spec, k)]:
            del variables[key]  # wiring constants and development switches: accepted, never advertised
        result[name] = dict(sorted(variables.items()))
    return result


def _internal(spec: ServiceSpec, name: str) -> bool:
    return name in TUNING_VARS or any(fnmatchcase(name, pattern) for pattern in spec.internal)


def shared_by_several(data: dict[str, dict[str, Variable]]) -> dict[str, list[str]]:
    """``{variable: [services]}`` for variables more than one service uses: they are set once, under ALL."""
    users: dict[str, list[str]] = {}
    for service, variables in data.items():
        for name in variables:
            users.setdefault(name, []).append(service)
    return {name: services for name, services in sorted(users.items()) if len(services) > 1}


MACHINES_EXAMPLE = """\
[machines.pc]                      # the Windows PC with the sound card
address = "192.168.1.20"           # an IP or a host name: no http://, no port
services = ["microphone", "speaker"]

[machines.server]                  # brain and everything that thinks (Python 3.12+ for ai-agent)
address = "192.168.1.10"
services = ["brain", "ai-agent", "stt", "tts"]

[machines.pi]                      # the Raspberry Pi wired to the motors (MOCK_HARDWARE = 0 under [env.stepper] for real motors)
address = "192.168.1.30"
services = ["stepper"]
# ports = { stepper = 18005 }      # a machine's ports = {..} only to deviate from services.toml; every caller follows"""


def toml_value(text: str) -> str:
    """``text`` as a TOML value: numbers and booleans stay bare, anything else is a string."""
    if re.fullmatch(r"-?(0|[1-9]\d*)(\.\d+)?", text) or text in ("true", "false"):
        return text
    if text == "":
        return '""'
    if "'" not in text and "\n" not in text and text == text.strip():
        return f"'{text}'"  # a literal string: nothing to escape
    return json.dumps(text, ensure_ascii=False)


def _variable(name: str, default: str, help_text: str, *, secret: bool, note: str = "") -> list[str]:
    text = " ".join(part for part in (note, help_text) if part)
    lines = [f"# {part}" for part in textwrap.wrap(text, width=108)] if text else []
    if secret:
        return [*lines, f'{name} = ""']  # active and empty: fill in the ones you use
    return [*lines, f"#{name} = {toml_value(default)}"]


def render_template(registry: Registry, data: dict[str, dict[str, Variable]]) -> str:
    out = [
        "# ROBOT: the single file of truth of the OBLIVION deployment. Copy to robot.toml (git-ignored), fill it in, and put the",
        "# same file on every machine. It holds the layout AND every setting and key of every service.",
        "#",
        "#   [machines.<name>]   where each machine is and which services run there. That is all a machine needs: the port of each",
        "#                       service is in services.toml, the URL of every service on another machine, each machine's bind",
        "#                       address and every SERVICE_HOST / SERVICE_PORT / *_BASE_URL are derived (`oblivion.py topology`).",
        "#   [env]               a variable once, for every service that uses it (a log level, an OpenAI key STT and ai-agent share).",
        "#   [env.<service>]     one service's own variables. It wins over [env]. Each service runs on exactly one machine, so",
        "#                       nothing here is per machine.",
        "#",
        "# A line that starts with `#NAME = value` is commented out and shows the default: uncomment and edit only what you want to",
        "# change. A line without `#` is active: the secrets (keys) are listed empty, fill in the ones you use. Values may be strings,",
        "# numbers or true/false. Only the settings worth changing are listed: the routes between services, service names, tuning",
        "# knobs and development switches keep their defaults.",
        "#",
        "# Keys in this file reach every machine you copy it to. To keep a key off a machine, leave it out of the copy that machine",
        "# gets and put it in that machine's own secrets/<machine>.env instead (lines NAME=value as SERVICE__NAME=value, or",
        "# ALL__NAME=value), which wins over this file.",
        "#",
        "# Generated by scripts/env_inventory.py from the services' .env.example files and source code. Do not edit the",
        "# structure by hand: run the script (tests fail when this file no longer lists everything the services read).",
        "",
        "# " + "=" * 96,
        "# THE ROBOT: machines and where the services run (every service on exactly one machine)",
        "# " + "=" * 96,
        MACHINES_EXAMPLE,
        "",
        "# " + "=" * 96,
        "# [env]: one value for every service that uses the variable",
        "# " + "=" * 96,
        "[env]",
        "# Shared logging (every service):",
    ]
    for variable, (default, help_text) in SHARED.items():
        out += _variable(variable, default, help_text, secret=is_secret(variable))
    several = shared_by_several(data)
    out += ["", "# Used by several services, so set once here instead of once per service:"]
    for variable, services in several.items():
        first = data[services[0]][variable]
        out += _variable(variable, first.default or "", first.help, secret=is_secret(variable), note=f"used by {', '.join(services)}.")
    for name, spec in registry.services.items():
        out += ["", "# " + "=" * 96, f"# [env.{name}]   default port {spec.port}", "# " + "=" * 96, f"[env.{name}]"]
        out += [f"# Computed by the deploy tool, not set here: {' '.join(sorted(computed_variables(spec)))}"]
        if spec.require_any:
            out += ["# The agent is available only when at least one provider key below, or OLLAMA_URL, is set."]
        required = {rule.key: rule.when for rule in spec.require}
        for variable in data[name].values():
            if variable.name in several:
                continue  # listed once, under [env]
            note = ""
            if variable.name in required:
                condition = ", ".join(f"{k}={v}" for k, v in required[variable.name].items())
                note = f"REQUIRED{' when ' + condition if condition else ''}."
            help_text = "" if variable.help.lower().startswith("required") else variable.help
            out += _variable(variable.name, variable.default or "", help_text, secret=is_secret(variable.name), note=note)
    return "\n".join(out) + "\n"


def build() -> str:
    registry = load_registry(ROOT / "services.toml")
    return render_template(registry, inventory(registry))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help=f"write {TEMPLATE.relative_to(ROOT)}")
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed template is out of date")
    args = parser.parse_args(argv)
    text = build()
    if args.write:
        TEMPLATE.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {TEMPLATE.relative_to(ROOT)} ({text.count(chr(10))} lines)")
        return 0
    if args.check:
        current = TEMPLATE.read_text(encoding="utf-8") if TEMPLATE.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print(f"{TEMPLATE.relative_to(ROOT)} is out of date: run scripts/env_inventory.py --write", file=sys.stderr)
            return 1
        return 0
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
