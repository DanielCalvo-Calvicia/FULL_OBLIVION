"""Builds the shared-logging wheel and puts it in ``wheels/``, so a machine that only cloned this repository
(no workspace next to it) can still install the library.

    brain_microservice/windows/Scripts/python.exe deployment/scripts/bundle_shared_logging.py [--source PATH]

``services.toml`` [libraries.shared-logging] lists ``path`` first (the workspace checkout) and ``wheel_dir``
second, so a developer machine keeps using the live source and every other machine uses this wheel.
``oblivion validate`` warns when the wheel is older than the checkout. Run this after every version change of
shared-logging and commit the new wheel. Stdlib only.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT.parent / "shared-logging"
WHEELS = ROOT / "wheels"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help=f"shared-logging checkout (default {DEFAULT_SOURCE})")
    args = parser.parse_args(argv)
    if not (args.source / "pyproject.toml").exists():
        print(f"error: {args.source} is not a shared-logging checkout (no pyproject.toml)", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [sys.executable, "-m", "pip", "wheel", "--quiet", "--no-deps", "--wheel-dir", tmp, str(args.source)],
            check=True,
        )
        (wheel,) = Path(tmp).glob("shared_logging-*.whl")
        WHEELS.mkdir(exist_ok=True)
        for old in WHEELS.glob("shared_logging-*.whl"):
            old.unlink()
        shutil.copy2(wheel, WHEELS / wheel.name)
    print(f"wheels/{wheel.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
