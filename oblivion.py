#!/usr/bin/env python3
"""The command people type: python oblivion.py <command> --host <machine>. The same as main.py."""
import sys

if sys.version_info < (3, 11):
    sys.exit("oblivion needs Python 3.11 or newer (found %d.%d)" % sys.version_info[:2])

from infrastructure.inbound.cli.cli import main

if __name__ == "__main__":
    sys.exit(main())
