"""Start a service that does not read a ``.env`` itself, loading its ``.env`` file first.

Run as a script by ``native_runtime.start``, with the service's own virtualenv Python (standard library only):

    python service_runner.py --env-file FILE -- SERVICE_ENTRY.py [args]

The settings come from FILE and nowhere else: the deploy tool put none of them in the environment, and it removed
any variable of the same name that the machine or the operator's shell had. As python-dotenv does for the services
that use it, a variable that is already set is left alone. Then the entry script runs as ``__main__`` with the
service folder first on ``sys.path``, exactly as ``python main.py`` would run it.

This runs INSIDE the service's Python, whose own packages are called ``domain``, ``application`` and ``infrastructure``
too. So nothing of this project is imported by package name: the one helper it needs (the .env parser, standard library
only) is loaded from its file, and nothing of the tool stays behind in the process.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import runpy
import sys
from pathlib import Path

TOOL_DIRECTORY = Path(__file__).resolve().parent
TOOL_ROOT = TOOL_DIRECTORY.parents[2]
DOTENV_PARSER = TOOL_ROOT / "domain" / "rules" / "dotenv.py"


def load_env_file(path: Path) -> dict[str, str]:
    spec = importlib.util.spec_from_file_location("_oblivion_dotenv", DOTENV_PARSER)
    if spec is None or spec.loader is None:
        raise SystemExit(f"service_runner: cannot load {DOTENV_PARSER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.parse_env(path.read_text(encoding="utf-8"))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no service entry point given after --")
    entry = Path(command[0]).resolve()
    if not args.env_file.is_file():
        print(f"service_runner: env file {args.env_file} does not exist", file=sys.stderr)
        return 2

    for key, value in load_env_file(args.env_file).items():
        os.environ.setdefault(key, value)

    # The tool's own folders must never shadow the service's modules.
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() not in (TOOL_DIRECTORY, TOOL_ROOT)]
    sys.path.insert(0, str(entry.parent))
    sys.argv = [str(entry), *command[1:]]
    runpy.run_path(str(entry), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
