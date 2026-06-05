import asyncio

from composition_root.setup.setup import setup
from infrastructure.config import resolve_environment
from infrastructure.logger import configure_logging, get_logger

logger = get_logger(__name__)

if __name__ == "__main__":
    environment = configure_logging(resolve_environment())
    try:
        logger.info("TTS microservice entrypoint invoked environment=%s", environment)
        asyncio.run(setup())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting.")
