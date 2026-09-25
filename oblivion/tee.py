"""Run a service, copying its output to this console and to its log file.

Used by ``runtime.native_start`` on Windows so every service gets its own visible window. Run as a script (not
imported), stdlib only:  ``python tee.py --log FILE --pid-file FILE -- COMMAND...``
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


_RECORD = re.compile(r"^\d{4}-\d\d-\d\dT\S+\s+([A-Z]+)")
_SHOWN_LEVELS = {"ERROR", "CRITICAL", "FATAL"}
STREAM_MARKER = "stream_stage"


def show_on_console(line: str, mode: str) -> bool:
    """Console filter by ``mode``: ``all``; ``stream`` (errors and full stream events, records carrying
    ``stream_stage``); ``errors`` (errors only).

    Anything that is not a log record (a traceback, a crash printed by Python) is always shown. The log file is
    never filtered.
    """
    if mode == "all":
        return True
    with_stream = mode != "errors"
    text = line.strip()
    if text.startswith("{"):
        try:
            record = json.loads(text)
        except ValueError:
            return True
        if isinstance(record, dict) and "level" in record:
            return str(record["level"]).upper() in _SHOWN_LEVELS or (with_stream and STREAM_MARKER in record)
        return True
    match = _RECORD.match(text)
    if match is None:
        return True
    return match.group(1) in _SHOWN_LEVELS or (with_stream and f"{STREAM_MARKER}=" in text)


def _forget_pid(pid_file: Path) -> None:
    """The service is gone: do not let a leftover window make it look alive."""
    try:
        if pid_file.read_text().strip() == str(os.getpid()):
            pid_file.unlink()
    except OSError:
        pass


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--pid-file", required=True)
    parser.add_argument("--name", default="service")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"=== {args.name}: {' '.join(command)}", flush=True)
    mode = os.environ.get("OBLIVION_CONSOLE_FILTER", "stream").strip().lower()
    if mode not in {"all", "stream", "errors"}:
        mode = "stream"
    if mode != "all":
        shown = "errors only" if mode == "errors" else "errors and stream events only"
        print(f"(console shows {shown}; the full log is in {args.log})", flush=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with open(args.log, "ab") as log:
        try:
            child = subprocess.Popen(  # noqa: S603
                command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
        except OSError as error:
            message = f"could not start {args.name}: {error}\n"
            sys.stdout.write(message)
            log.write(message.encode())
            code = 127
        else:
            assert child.stdout is not None
            while True:
                try:
                    chunk = child.stdout.readline()
                except KeyboardInterrupt:
                    continue  # the child gets the same Ctrl+C; keep copying until it ends
                if not chunk:
                    break
                log.write(chunk)
                log.flush()
                text = chunk.decode("utf-8", errors="replace")
                if show_on_console(text, mode):
                    sys.stdout.write(text)
                    sys.stdout.flush()
            code = child.wait()
        footer = f"\n=== {args.name} exited with code {code}\n"
        log.write(footer.encode())
    _forget_pid(Path(args.pid_file))
    sys.stdout.write(footer)
    sys.stdout.flush()
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            input("Press Enter to close this window...")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
