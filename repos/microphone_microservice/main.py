import asyncio

from composition_root.setup.setup import setup
from composition_root.runtime.logger import get_logger


logger = get_logger("main")

if __name__ == "__main__":
    logger.info("Starting microphone microservice process")
    try:
        asyncio.run(setup())
        logger.info("Microphone microservice process exited normally")
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting.")
