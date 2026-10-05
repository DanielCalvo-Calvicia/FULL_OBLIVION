#!/usr/bin/env python3
"""Entry point: python main.py <command> --host <machine>  (Python 3.11+, standard library only).

``oblivion.py`` is the same command under the name people type; ``launch.py`` starts everything on one machine.
"""
import sys

if sys.version_info < (3, 11):
    sys.exit("oblivion needs Python 3.11 or newer (found %d.%d)" % sys.version_info[:2])

from infrastructure.inbound.cli.cli import main

if __name__ == "__main__":
    sys.exit(main())
