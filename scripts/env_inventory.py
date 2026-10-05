"""Inventory of every environment variable of every deployable service, and the settings files built from it.

    brain_microservice/windows/Scripts/python.exe deployment/scripts/env_inventory.py            # print every generated file
    brain_microservice/windows/Scripts/python.exe deployment/scripts/env_inventory.py --write    # refresh config/services/*.toml and config/local/*.example.toml
    brain_microservice/windows/Scripts/python.exe deployment/scripts/env_inventory.py --check    # fail if they are out of date

Needs the development workspace next to this repository (it reads each service's source). It writes, for every service,
``config/services/<name>.toml`` (the project's documented defaults, committed), ``config/services/all.toml`` (what several
services share) and ``config/local/<name>.example.toml`` (just the secrets, for you to copy to ``config/local/``);
``tests/test_settings_files.py`` fails when they no longer list everything the services read.

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

from domain.entities.catalogue import Catalogue  # noqa: E402
from domain.entities.service_spec import ServiceSpec  # noqa: E402
from domain.rules.dotenv import parse_env  # noqa: E402
from domain.rules.env_names import SHARED_LOGGING_VARS, TUNING_VARS, computed_variables, is_secret  # noqa: E402
from infrastructure.config.catalogue_loader import load_catalogue  # noqa: E402

WORKSPACE = ROOT.parent
CONFIG = ROOT / "config"
SKIP_DIRS = {"windows", "vendor", "tests", "testclear", "__pycache__", ".git", "node_modules", "old", "build", "dist"}

# Variables of shared-logging: every service reads them, so config/services/all.toml sets one for all services at once.
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
assert set(SHARED) == set(SHARED_LOGGING_VARS) - TUNING_VARS, "keep SHARED in step with domain/rules/env_names.py"

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


def inventory(catalogue: Catalogue, workspace: Path = WORKSPACE) -> dict[str, dict[str, Variable]]:
    """``{service: {variable: Variable}}`` for every deployable service (computed and shared variables excluded)."""
    result: dict[str, dict[str, Variable]] = {}
    for name, spec in catalogue.services.items():
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
        for key, value in spec.env.items():  # catalogue.toml sets it, so that is what a deployed machine gets
            variable = variables.setdefault(key, Variable(key))
            variable.default = value
            variable.help = f"{variable.help} (catalogue.toml presets {key}={value})".strip()
            variable.sources.add("catalogue")
        for hidden in SHARED_LOGGING_VARS | computed_variables(spec):
            variables.pop(hidden, None)  # shared-logging names are in all.toml; the rest the tool computes
        for key in [k for k in variables if _internal(spec, k)]:
            del variables[key]  # wiring constants and development switches: accepted, never advertised
        result[name] = dict(sorted(variables.items()))
    return result


def _internal(spec: ServiceSpec, name: str) -> bool:
    return name in TUNING_VARS or any(fnmatchcase(name, pattern) for pattern in spec.internal)


def shared_by_several(data: dict[str, dict[str, Variable]]) -> dict[str, list[str]]:
    """``{variable: [services]}`` for variables more than one service uses: they are set once, in all.toml."""
    users: dict[str, list[str]] = {}
    for service, variables in data.items():
        for name in variables:
            users.setdefault(name, []).append(service)
    return {name: services for name, services in sorted(users.items()) if len(services) > 1}


def toml_value(text: str) -> str:
    """``text`` as a TOML value: numbers and booleans stay bare, anything else is a string."""
    if re.fullmatch(r"-?(0|[1-9]\d*)(\.\d+)?", text) or text in ("true", "false"):
        return text
    if text == "":
        return '""'
    if "'" not in text and "\n" not in text and text == text.strip():
        return f"'{text}'"  # a literal string: nothing to escape
    return json.dumps(text, ensure_ascii=False)


def _variable(name: str, default: str, help_text: str, *, secret: bool, note: str = "", where: str = "") -> list[str]:
    """The comment and the (commented-out) assignment of one setting. A secret is never active in a committed file."""
    text = " ".join(part for part in (note, help_text) if part)
    lines = [f"# {part}" for part in textwrap.wrap(text, width=108)] if text else []
    if secret:
        lines.append(f"# SECRET: put it in {where}, not in this committed file." if where else "# SECRET.")
        return [*lines, f'#{name} = ""']
    return [*lines, f"#{name} = {toml_value(default)}"]


def _required(spec: ServiceSpec) -> dict[str, dict[str, str]]:
    return {rule.key: rule.when for rule in spec.require}


def _required_note(required: dict[str, dict[str, str]], name: str) -> str:
    if name not in required:
        return ""
    condition = ", ".join(f"{k}={v}" for k, v in required[name].items())
    return f"REQUIRED{' when ' + condition if condition else ''}."


def render_service_file(name: str, spec: ServiceSpec, variables: dict[str, Variable], several: dict[str, list[str]]) -> str:
    """``config/services/<name>.toml``: which code the service runs and its own settings, at their defaults."""
    out = [
        f"# SETTINGS OF {name.upper()} (default port {spec.port}). One file per service: which code it runs and its own settings.",
        "#",
        "# This is the project's default and is committed: every line is commented out and shows the default. Uncomment and edit a line",
        f"# here to change it for everyone; put YOUR values and every key in config/local/{name}.toml (git-ignored, same shape, wins",
        "# over this file). Settings several services share are in config/services/all.toml.",
        "#",
        "# Which code to deploy: set at most one of branch, tag or commit. `oblivion.py deploy|update --branch " + name + "=<ref>`",
        "# overrides it for one run.",
        f"#branch = {toml_value(spec.branch)}",
        "#tag = 'v1.0.0'",
        "#commit = '0123abc'",
        "#",
        "# How it runs: native (a process of this machine) or docker. A port only to deviate from the catalogue; git only to deploy",
        "# another repository or a local checkout.",
        '#runtime = "native"',
        f"#port = {spec.port}",
        "#git = 'https://github.com/you/fork.git'",
        "#",
        "# Generated by scripts/env_inventory.py from the service's .env.example and source code. Do not edit the structure by hand.",
        "",
        "[env]",
        f"# Computed by the deploy tool, not set here: {' '.join(sorted(computed_variables(spec)))}",
    ]
    if spec.require_any:
        out += ["# The agent is available only when at least one provider key below, or OLLAMA_URL, is set."]
    required = _required(spec)
    shared = [v for v in variables if v in several]
    if shared:
        out += [f"# Shared with other services, so they are in config/services/all.toml: {', '.join(shared)}"]
    for variable in variables.values():
        if variable.name in several:
            continue
        note = _required_note(required, variable.name)
        help_text = "" if variable.help.lower().startswith("required") else variable.help
        out += _variable(variable.name, variable.default or "", help_text, secret=is_secret(variable.name), note=note, where=f"config/local/{name}.toml")
    return "\n".join(out) + "\n"


def render_all_file(catalogue: Catalogue, data: dict[str, dict[str, Variable]]) -> str:
    """``config/services/all.toml``: a setting once, for every service that uses it."""
    out = [
        "# SETTINGS SHARED BY SEVERAL SERVICES. A value here reaches every service that uses the variable and no other (a log level",
        "# every service reads, the OpenAI key STT and ai-agent both need). A service's own file wins over this one.",
        "#",
        "# This is the project's default and is committed: every line is commented out and shows the default. Put YOUR values and every",
        "# key in config/local/all.toml (git-ignored, same shape, wins over this file).",
        "#",
        "# Generated by scripts/env_inventory.py from the services' .env.example files and source code. Do not edit the structure by hand.",
        "",
        "[env]",
        "# Shared logging (every service):",
    ]
    for variable, (default, help_text) in SHARED.items():
        out += _variable(variable, default, help_text, secret=is_secret(variable), where="config/local/all.toml")
    out += ["", "# Used by several services, so set once here instead of once per service:"]
    for variable, services in shared_by_several(data).items():
        first = data[services[0]][variable]
        out += _variable(
            variable, first.default or "", first.help, secret=is_secret(variable),
            note=f"Used by {', '.join(services)}.", where="config/local/all.toml",
        )
    return "\n".join(out) + "\n"


def render_local_example(label: str, variables: list[Variable], who: str) -> str:
    """``config/local/<name>.example.toml``: only the secrets, active and empty, for you to copy and fill in."""
    out = [
        f"# YOUR PRIVATE SETTINGS FOR {label.upper()}. Copy this file to config/local/{label}.toml (git-ignored) and fill in the keys you use.",
        "# Anything else from the matching file in config/services/ can be copied here to override it on this robot.",
        f"# {who}",
        "",
        "[env]",
    ]
    for variable in variables:
        text = " ".join(part for part in (variable.help,) if part)
        out += [f"# {part}" for part in textwrap.wrap(text, width=108)] if text else []
        out += [f'{variable.name} = ""']
    return "\n".join(out) + "\n"


def build_files(catalogue: Catalogue | None = None) -> dict[Path, str]:
    """``{path relative to config/: text}`` of every generated file."""
    catalogue = catalogue or load_catalogue()
    data = inventory(catalogue)
    several = shared_by_several(data)
    files: dict[Path, str] = {Path("services/all.toml"): render_all_file(catalogue, data)}
    shared_secrets = [data[services[0]][name] for name, services in several.items() if is_secret(name)]
    if shared_secrets:
        users = sorted({s for name, services in several.items() if is_secret(name) for s in services})
        files[Path("local/all.example.toml")] = render_local_example("all", shared_secrets, f"Shared keys: used by {', '.join(users)}.")
    for name, spec in catalogue.services.items():
        files[Path(f"services/{name}.toml")] = render_service_file(name, spec, data[name], several)
        own_secrets = [v for v in data[name].values() if is_secret(v.name) and v.name not in several]
        if own_secrets:
            files[Path(f"local/{name}.example.toml")] = render_local_example(name, own_secrets, f"Keys of {name} only.")
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="write config/services/*.toml and config/local/*.example.toml")
    parser.add_argument("--check", action="store_true", help="exit 1 when a committed file is out of date")
    args = parser.parse_args(argv)
    files = build_files()
    if args.write:
        for relative, text in files.items():
            target = CONFIG / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote config/{relative.as_posix()} ({text.count(chr(10))} lines)")
        return 0
    if args.check:
        stale = [
            f"config/{relative.as_posix()}" for relative, text in files.items()
            if not (CONFIG / relative).exists() or (CONFIG / relative).read_text(encoding="utf-8").replace("\r\n", "\n") != text
        ]
        if stale:
            print(f"out of date: {', '.join(stale)}: run scripts/env_inventory.py --write", file=sys.stderr)
            return 1
        return 0
    for relative, text in files.items():
        sys.stdout.write(f"\n===== config/{relative.as_posix()} =====\n{text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
