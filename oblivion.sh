#!/usr/bin/env bash
# Linux / Raspberry Pi launcher: finds a Python 3.11+ and runs the CLI.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for py in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    exec "$py" "$here/oblivion.py" "$@"
  fi
done
echo "oblivion needs Python 3.11+. On Raspberry Pi OS Bookworm: sudo apt install python3 python3-venv git" >&2
exit 2
