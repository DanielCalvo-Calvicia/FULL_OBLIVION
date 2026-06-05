import asyncio

from composition_root.setup.setup import setup
from domain.console import console_log

if __name__ == "__main__":
    try:
        asyncio.run(setup())
    except KeyboardInterrupt:
        console_log("main", "keyboard interrupt received; exiting", level="warn")
